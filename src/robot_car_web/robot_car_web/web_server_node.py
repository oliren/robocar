#!/usr/bin/env python3
"""
Robot Car Web Server — FastAPI application + entry point.

Routes
------
GET  /               HTML control page
GET  /video_feed     MJPEG stream  (multipart/x-mixed-replace)
GET  /camera/status  JSON camera status
GET  /servo/status   JSON servo status
WS   /ws             Drive + servo commands
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import rclpy
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from rclpy.executors import ExternalShutdownException

from .camera   import CameraStream
from .ros_node import WebControlNode
from .servo    import ServoController

log = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent

# ── Shared state ──────────────────────────────────────────────────────────────
_node:        Optional[WebControlNode]   = None
_camera:      Optional[CameraStream]     = None
_servo:       Optional[ServoController]  = None
_spin_thread: Optional[threading.Thread] = None

# Set during app shutdown so long-lived connections (MJPEG stream, WebSocket)
# break out of their infinite loops instead of blocking a graceful shutdown.
_shutdown = asyncio.Event()


# ── ROS spin helper ───────────────────────────────────────────────────────────
def _ros_spin(node: WebControlNode) -> None:
    try:
        rclpy.spin(node)
    except ExternalShutdownException:
        pass
    except Exception as exc:
        log.error('ROS spin error: %s', exc)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _node, _camera, _servo, _spin_thread

    rclpy.init()
    _node = WebControlNode()
    _spin_thread = threading.Thread(
        target=_ros_spin, args=(_node,), daemon=True, name='ros-spin',
    )
    _spin_thread.start()
    log.info('ROS 2 node started')

    _camera = CameraStream(width=640, height=480, fps=15, bitrate=2_000_000)
    _servo  = ServoController()

    yield

    log.info('Shutting down…')
    _shutdown.set()   # release long-lived loops (MJPEG stream, WebSocket)

    if _node and rclpy.ok():
        _node.stop()
    if _node:
        try:
            _node.destroy_node()
        except Exception as exc:
            log.debug('destroy_node: %s', exc)
    if rclpy.ok():
        rclpy.shutdown()
    if _spin_thread and _spin_thread.is_alive():
        _spin_thread.join(timeout=2.0)

    if _servo:
        _servo.stop()
    if _camera:
        _camera.stop()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title='Robot Car Control', lifespan=lifespan)

app.mount(
    '/static',
    StaticFiles(directory=str(_PKG_DIR / 'static')),
    name='static',
)
templates = Jinja2Templates(directory=str(_PKG_DIR / 'templates'))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get('/')
async def index(request: Request):
    cam   = _camera.status if _camera else {}
    servo = _servo.status  if _servo  else {}
    config = {
        'camera_active': cam.get('active', False),
        'camera_width':  cam.get('width',  640),
        'camera_height': cam.get('height', 480),
        'camera_fps':    cam.get('fps',    15),
        'servo_active':  servo.get('active', False),
        'servo_pan':     servo.get('pan',    90.0),
        'servo_tilt':    servo.get('tilt',   90.0),
    }
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={'config': config},
    )


@app.get('/camera/status', response_class=JSONResponse)
async def camera_status():
    return _camera.status if _camera else {'active': False, 'frames': 0}


@app.get('/servo/status', response_class=JSONResponse)
async def servo_status():
    return _servo.status if _servo else {'active': False, 'pan': 90, 'tilt': 90}


async def _mjpeg_generator():
    yield b'--mjpegboundary\r\n'
    try:
        while not _shutdown.is_set():
            if _camera is None or not _camera.active:
                await asyncio.sleep(0.5)
                continue
            frame: Optional[bytes] = await asyncio.to_thread(
                _camera.output.wait_for_frame, 1.0
            )
            if frame is None:
                continue
            yield (
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                b'\r\n' + frame + b'\r\n--mjpegboundary\r\n'
            )
    except GeneratorExit:
        pass


@app.get('/video_feed')
async def video_feed():
    if _camera is None or not _camera.active:
        return JSONResponse({'error': 'Camera not available'}, status_code=503)
    return StreamingResponse(
        _mjpeg_generator(),
        media_type='multipart/x-mixed-replace; boundary=mjpegboundary',
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'},
    )


@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    log.debug('Client connected: %s', ws.client)
    shutdown_wait = asyncio.ensure_future(_shutdown.wait())
    try:
        while not _shutdown.is_set():
            # Race the client message against server shutdown so a restart
            # isn't blocked by this idle receive while a browser is connected.
            recv = asyncio.ensure_future(ws.receive_text())
            done, _ = await asyncio.wait(
                {recv, shutdown_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if recv not in done:
                recv.cancel()
                break
            data = json.loads(recv.result())
            match data.get('type'):

                case 'cmd_vel':
                    if _node:
                        _node.send_cmd_vel(
                            data.get('linear',  0.0),
                            data.get('angular', 0.0),
                        )

                case 'stop':
                    if _node:
                        _node.stop()

                case 'servo':
                    if _servo:
                        await asyncio.to_thread(
                            _servo.set,
                            data.get('pan',  90.0),
                            data.get('tilt', 90.0),
                        )

                case 'servo_center':
                    if _servo:
                        await asyncio.to_thread(_servo.center)

    except (WebSocketDisconnect, Exception) as exc:
        log.debug('Client disconnected: %s', exc)
    finally:
        shutdown_wait.cancel()
        if _node:
            _node.stop()


# ── Entry point ───────────────────────────────────────────────────────────────
def main(args=None):
    logging.basicConfig(
        level=logging.INFO,
        format='[%(name)s] %(levelname)s: %(message)s',
    )

    for name, path in [
        ('static dir',    _PKG_DIR / 'static'),
        ('templates dir', _PKG_DIR / 'templates'),
    ]:
        if not path.is_dir():
            log.error('Missing %s: %s', name, path)
            raise SystemExit(1)

    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = 'localhost'

    print(f'\n  ✅  Robot web server starting')
    print(f'  🌐  http://{ip}:8080\n')

    try:
        uvicorn.run(
            app,
            host='0.0.0.0',
            port=8080,
            log_level='warning',
            # Force-drop any still-open connections a few seconds after
            # SIGTERM so a restart with a browser attached doesn't hang.
            timeout_graceful_shutdown=5,
        )
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

