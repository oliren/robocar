'use strict';

(function () {

  const cfg = window.APP_CONFIG ?? {
    camera_active: false,
    camera_width: 640, camera_height: 480, camera_fps: 15,
    servo_active: false, servo_pan: 90, servo_tilt: 90,
  };

  const el   = id  => document.getElementById(id);
  const qAll = sel => document.querySelectorAll(sel);

  // ── Status ─────────────────────────────────────────────────────────────────
  const Status = {
    set(on) {
      el('dot').className      = on ? 'dot on' : 'dot';
      el('st-txt').textContent = on ? 'Connected' : 'Reconnecting…';
    },
  };

  // ── Drive ──────────────────────────────────────────────────────────────────
  const Drive = {
    speed: 0.5,
    sendCmd(linear, angular) {
      const l = parseFloat((linear  * this.speed).toFixed(3));
      const a = parseFloat((angular * this.speed).toFixed(3));
      WS.send({ type: 'cmd_vel', linear: l, angular: a });
      qAll('[data-ind="linear"]') .forEach(e => { e.textContent = l.toFixed(2); });
      qAll('[data-ind="angular"]').forEach(e => { e.textContent = a.toFixed(2); });
    },
    stop() {
      WS.send({ type: 'stop' });
      qAll('[data-ind="linear"], [data-ind="angular"]')
        .forEach(e => { e.textContent = ' 0.00'; });
    },
  };

  // ── Servo ──────────────────────────────────────────────────────────────────
  const Servo = {
    pan:      cfg.servo_pan  ?? 90,
    tilt:     cfg.servo_tilt ?? 90,
    STEP:     45,
    PAN_MIN:  0,   PAN_MAX:  180,
    TILT_MIN: 45,  TILT_MAX: 135,

    _send() {
      WS.send({ type: 'servo', pan: this.pan, tilt: this.tilt });
      el('sv-pan') .textContent = Math.round(this.pan);
      el('sv-tilt').textContent = Math.round(this.tilt);
    },

    panLeft()  { this.pan  = Math.max(this.PAN_MIN,  this.pan  - this.STEP); this._send(); },
    panRight() { this.pan  = Math.min(this.PAN_MAX,  this.pan  + this.STEP); this._send(); },
    tiltUp()   { this.tilt = Math.min(this.TILT_MAX, this.tilt + this.STEP); this._send(); },
    tiltDown() { this.tilt = Math.max(this.TILT_MIN, this.tilt - this.STEP); this._send(); },
    center()   {
      this.pan = 90; this.tilt = 90;
      WS.send({ type: 'servo_center' });
      el('sv-pan') .textContent = '90';
      el('sv-tilt').textContent = '90';
    },
  };

  // ── WebSocket ──────────────────────────────────────────────────────────────
  const WS = {
    socket: null, _timer: null,
    connect() {
      this.socket = new WebSocket(`ws://${location.host}/ws`);
      this.socket.onopen  = () => { Status.set(true); clearTimeout(this._timer); };
      this.socket.onclose =
      this.socket.onerror = () => {
        Status.set(false);
        this._timer = setTimeout(() => this.connect(), 2000);
      };
    },
    send(data) {
      if (this.socket?.readyState === WebSocket.OPEN)
        this.socket.send(JSON.stringify(data));
    },
  };

  // ── Drive Joystick ─────────────────────────────────────────────────────────
  function initJoystick() {
    const zone  = el('joy');
    const thumb = el('thumb');
    const MAX   = 52;
    let active  = false, rect;

    zone.addEventListener('pointerdown', e => {
      active = true;
      rect   = zone.getBoundingClientRect();
      zone.setPointerCapture(e.pointerId);
      thumb.classList.add('drag');
      move(e.clientX, e.clientY);
    });
    zone.addEventListener('pointermove', e => { if (active) move(e.clientX, e.clientY); });
    zone.addEventListener('pointerup',     release);
    zone.addEventListener('pointercancel', release);

    function move(x, y) {
      const cx = rect.left + rect.width  / 2;
      const cy = rect.top  + rect.height / 2;
      let dx = x - cx, dy = y - cy;
      const dist = Math.hypot(dx, dy);
      if (dist > MAX) { dx *= MAX / dist; dy *= MAX / dist; }
      thumb.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
      Drive.sendCmd(-dy / MAX, -dx / MAX);
    }
    function release() {
      if (!active) return;
      active = false;
      thumb.classList.remove('drag');
      thumb.style.transform = 'translate(-50%, -50%)';
      Drive.stop();
    }
  }

  // ── Drive D-Pad ────────────────────────────────────────────────────────────
  function initDPad() {
    qAll('.dpad .dp').forEach(btn => {
      const l = parseFloat(btn.dataset.l ?? 0);
      const a = parseFloat(btn.dataset.a ?? 0);
      let iv  = null;

      btn.addEventListener('pointerdown', e => {
        e.preventDefault();
        btn.setPointerCapture(e.pointerId);
        btn.classList.add('active');
        Drive.sendCmd(l, a);
        iv = setInterval(() => Drive.sendCmd(l, a), 80);
      });
      ['pointerup', 'pointercancel'].forEach(ev =>
        btn.addEventListener(ev, () => {
          btn.classList.remove('active');
          clearInterval(iv); iv = null;
          Drive.stop();
        })
      );
    });
  }

  // ── Camera D-Pad ───────────────────────────────────────────────────────────
  function initCamDPad() {
    const bindings = [
      ['cdp-up',  () => Servo.tiltDown()],
      ['cdp-dn',  () => Servo.tiltUp()  ],
      ['cdp-lft', () => Servo.panRight()],
      ['cdp-rgt', () => Servo.panLeft() ],
      ['cdp-ctr', () => Servo.center()  ],
    ];

    bindings.forEach(([id, action]) => {
      const btn = el(id);
      if (!btn) return;
      btn.addEventListener('pointerdown', e => {
        e.preventDefault();
        btn.setPointerCapture(e.pointerId);
        btn.classList.add('active');
        action();
      });
      ['pointerup', 'pointercancel'].forEach(ev =>
        btn.addEventListener(ev, () => btn.classList.remove('active'))
      );
    });
  }


  // ── Speed ──────────────────────────────────────────────────────────────────
  function initSpeed() {
    qAll('.spd-range').forEach(r =>
      r.addEventListener('input', () => {
        Drive.speed = r.value / 100;
        qAll('.spd-range').forEach(s  => { s.value = r.value; });
        qAll('.spd-val')  .forEach(lb => { lb.textContent = r.value + '%'; });
      })
    );
    qAll('.estop-btn').forEach(b =>
      b.addEventListener('click', () => Drive.stop())
    );
  }

  // ── Camera stream ──────────────────────────────────────────────────────────
  const Camera = {
    _started: false, _poll: null, _retry: null,
    start() {
      if (this._started) return;
      this._started = true;
      el('cam-img').src = '/video_feed';
    },
    onLoad() {
      el('cam-overlay').classList.add('hidden');
      clearTimeout(this._retry);
      if (!this._poll) {
        this._poll = setInterval(async () => {
          try {
            const s = await (await fetch('/camera/status')).json();
            if (s.active)
              el('cam-info').textContent =
                `${s.width}×${s.height} · MJPEG · ${s.fps} fps · frame ${s.frames}`;
          } catch (_) {}
        }, 2000);
      }
    },
    onError() {
      el('cam-overlay').classList.remove('hidden');
      el('cam-msg').textContent = '❌ Camera unavailable — retrying…';
      this._retry = setTimeout(() => {
        el('cam-img').src = `/video_feed?t=${Date.now()}`;
      }, 3000);
    },
  };
  window.Camera = Camera;

  // ── Tabs ───────────────────────────────────────────────────────────────────
  function initTabs() {
    qAll('.tab').forEach(btn =>
      btn.addEventListener('click', () => {
        Drive.stop();
        const tab = btn.dataset.tab;
        qAll('.tab')  .forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        qAll('.panel').forEach(p => p.classList.toggle('hidden',  p.id !== `pnl-${tab}`));
        if (tab === 'cam') Camera.start();
      })
    );
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  WS.connect();
  initTabs();
  initJoystick();
  initDPad();
  initCamDPad();
  initSpeed();
  Camera.start();

  el('sv-pan') .textContent = Math.round(cfg.servo_pan  ?? 90);
  el('sv-tilt').textContent = Math.round(cfg.servo_tilt ?? 90);

})();