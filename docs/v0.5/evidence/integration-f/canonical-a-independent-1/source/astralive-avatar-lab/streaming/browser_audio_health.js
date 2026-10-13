"use strict";
var SoulXAudioHealth = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // frontend/src/lib/previewAudioHealth.ts
  var previewAudioHealth_exports = {};
  __export(previewAudioHealth_exports, {
    AudioRouteGuard: () => AudioRouteGuard,
    PlayoutWatchdog: () => PlayoutWatchdog
  });
  var AudioRouteGuard = class {
    constructor(element, { devices = navigator.mediaDevices, log = () => {
    } } = {}) {
      this.element = element;
      this.devices = devices;
      this.log = log;
    }
    element;
    id = null;
    dead = false;
    onchange = () => {
      void this.check().catch((cause) => this.log("AudioRouteCheckFailed", { reason: String(cause) }));
    };
    devices;
    log;
    async pin(id) {
      if (this.dead) throw Error("audio route guard disposed");
      if (!id || ["default", "communications"].includes(id)) throw Error("concrete output device required");
      if (typeof this.element.setSinkId !== "function") throw Error("setSinkId unsupported");
      const list = await this.devices.enumerateDevices();
      if (this.dead) throw Error("audio route guard disposed");
      if (!list.some((x) => x.kind === "audiooutput" && x.deviceId === id)) throw Error("selected output unavailable");
      await this.element.setSinkId(id);
      if (this.dead) throw Error("audio route guard disposed");
      if (this.element.sinkId !== id) throw Error("audio output pin not applied");
      this.id = id;
      this.devices.addEventListener("devicechange", this.onchange);
      this.log("AudioSinkPinned", { concrete: true });
      return this;
    }
    // Only the isolated lab calls this. Product selection requires a user gesture.
    async pinBuiltIn() {
      const list = await this.devices.enumerateDevices();
      const device = list.find((x) => x.kind === "audiooutput" && !["", "default", "communications"].includes(x.deviceId) && /macbook|built.?in|内置/i.test(x.label));
      if (!device) throw Error("concrete built-in output unavailable or not authorized");
      return this.pin(device.deviceId);
    }
    async check() {
      if (this.dead || !this.id) return;
      const id = this.id;
      const list = await this.devices.enumerateDevices();
      if (this.dead) return;
      const found = list.some((x) => x.kind === "audiooutput" && x.deviceId === id);
      this.log("AudioDeviceChange", { selectedOutputAvailable: found, concreteSinkRetained: this.element.sinkId === id });
      if (!found) {
        this.log("AudioOutputUnavailable", { requiresOutputSelection: true });
        return false;
      }
      if (this.element.sinkId !== id) {
        await this.element.setSinkId(id);
        if (!this.dead) this.log("AudioSinkRestored", { concrete: true });
      }
      return true;
    }
    dispose() {
      this.dead = true;
      this.devices.removeEventListener("devicechange", this.onchange);
    }
  };
  var PlayoutWatchdog = class {
    previous = null;
    stalled = false;
    good = 0;
    started = null;
    stallMs;
    ratio;
    log;
    constructor({ stallMs = 600, ratio = 0.2, log = () => {
    } } = {}) {
      this.stallMs = stallMs;
      this.ratio = ratio;
      this.log = log;
    }
    get readyToRestart() {
      return this.stalled && this.good >= 2;
    }
    reset() {
      this.previous = null;
      this.stalled = false;
      this.good = 0;
      this.started = null;
    }
    sample(t, rows) {
      const audio = rows.find((x) => x.type === "inbound-rtp" && x.kind === "audio");
      const video = rows.find((x) => x.type === "inbound-rtp" && x.kind === "video");
      const playout = rows.find((x) => x.type === "media-playout" && x.kind === "audio");
      if (!audio || !video || !Number.isFinite(playout?.totalSamplesDuration)) return null;
      const current = {
        t,
        packets: audio.packetsReceived ?? 0,
        video: video.framesDecoded ?? 0,
        played: playout.totalSamplesDuration
      };
      const previous = this.previous;
      this.previous = current;
      if (!previous) return null;
      const dt = t - previous.t, dp = current.played - previous.played;
      if (dt <= 0 || dp < 0 || current.packets < previous.packets || current.video < previous.video) {
        this.reset();
        this.previous = current;
        return null;
      }
      const incoming = current.packets > previous.packets && current.video > previous.video;
      if (incoming && dp < dt * this.ratio) {
        this.started ??= previous.t;
        this.good = 0;
      } else {
        this.started = null;
        this.good = incoming && dp >= dt * this.ratio ? this.good + 1 : 0;
      }
      if (!this.stalled && this.started !== null && (t - this.started) * 1e3 >= this.stallMs) {
        this.stalled = true;
        const event = { durationMs: (t - this.started) * 1e3, audioPacketDelta: current.packets - previous.packets, playedDurationDelta: dp };
        this.log("AudioPlayoutStalled", event);
        return { state: "stalled", ...event };
      }
      const ap = audio.estimatedPlayoutTimestamp, vp = video.estimatedPlayoutTimestamp;
      const av = Number.isFinite(ap) && ap > 0 && Number.isFinite(vp) && vp > 0 ? ap - vp : null;
      if (this.stalled && this.good >= 3 && av !== null && Math.abs(av) <= 150) {
        this.stalled = false;
        this.log("AudioPlayoutRecovered", { estimatedAVOffsetMs: av });
        return { state: "recovered", estimatedAVOffsetMs: av };
      }
      return null;
    }
  };
  return __toCommonJS(previewAudioHealth_exports);
})();

if(typeof module!=='undefined')module.exports=SoulXAudioHealth;
