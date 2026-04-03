(function () {
  "use strict";

  function initAsciiScene() {
    const scene = document.getElementById("hero-ascii-scene");
    const canvas = document.getElementById("hero-ascii-canvas");
    const fallback = document.getElementById("hero-ascii-fallback");
    const hero = scene ? scene.closest(".hero") : null;
    if (!scene || !canvas || !fallback || !hero) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const farSet = [".", "'", "`", ":", ",", ";"];
    const edgeSet = [".", ":", "'", ",", "`"];
    const midSet = ["~", "-", "=", "+", ".", ":", "*"];
    const nearSet = ["@", "#", "%", "O", "0", "*", "+"];
    const tailSet = [".", ":", "'", "+", "*"];
    let cols = 0;
    let rows = 0;
    let cellW = 10;
    let cellH = 16;
    let width = 0;
    let height = 0;
    let fontSize = 14;

    let pointerX = -9999;
    let pointerY = -9999;
    let prevPointerX = -9999;
    let prevPointerY = -9999;
    let pointerActiveAt = 0;
    let pointerDown = false;
    let activePointerId = null;

    let charField = [];
    let decayField;
    let trailField;
    let glowField;
    let introField = [];
    let introResolved;
    let introUnresolved;
    let introResolvedCount = 0;
    let rafId = 0;
    let destroyed = false;
    let introStartTime = 0;
    const introDurationMs = 3000;

    function clamp(value, min, max) {
      return Math.max(min, Math.min(max, value));
    }

    function choose(items) {
      return items[(Math.random() * items.length) | 0];
    }

    function easeOutCubic(t) {
      return 1 - Math.pow(1 - t, 3);
    }

    function idx(x, y) {
      return y * cols + x;
    }

    function setCanvasSize() {
      width = scene.clientWidth;
      height = scene.clientHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      fontSize = Math.max(12, Math.min(16, Math.floor(width / 104)));
      ctx.font = fontSize + 'px "JetBrains Mono", Consolas, monospace';
      ctx.textBaseline = "top";

      const metrics = ctx.measureText("M");
      cellW = Math.max(8, Math.ceil(metrics.width));
      cellH = Math.max(12, Math.ceil(fontSize * 1.15));

      cols = Math.ceil(width / cellW);
      rows = Math.ceil(height / cellH);

      const fieldSize = cols * rows;
      charField = new Array(fieldSize).fill(" ");
      decayField = new Float32Array(fieldSize);
      trailField = new Float32Array(fieldSize);
      glowField = new Float32Array(fieldSize);
      introField = new Array(fieldSize);
      introResolved = new Uint8Array(fieldSize);
      introUnresolved = new Array(fieldSize);
      introResolvedCount = 0;
      for (let y = 0; y < rows; y += 1) {
        for (let x = 0; x < cols; x += 1) {
          const k = idx(x, y);
          const noiseSet = x % 3 === 0 ? nearSet : x % 2 === 0 ? midSet : edgeSet;
          introField[k] = choose(noiseSet);
          introUnresolved[k] = k;
        }
      }
    }

    function resolveIntroCells(targetResolvedCount) {
      if (!introResolved || !introUnresolved) return;
      const maxTarget = Math.min(targetResolvedCount, introResolved.length);
      while (introResolvedCount < maxTarget && introUnresolved.length > 0) {
        const pickIndex = (Math.random() * introUnresolved.length) | 0;
        const k = introUnresolved[pickIndex];
        introResolved[k] = 1;
        introResolvedCount += 1;
        introUnresolved[pickIndex] = introUnresolved[introUnresolved.length - 1];
        introUnresolved.pop();
      }
    }

    function baseChar(x, y, time) {
      const waveA = Math.sin(x * 0.17 + time * 0.48);
      const waveB = Math.cos(y * 0.21 - time * 0.36);
      const waveC = Math.sin((x + y) * 0.09 + time * 0.24);
      const waveD = Math.cos((x - y) * 0.07 - time * 0.18);
      const mix = waveA * 0.34 + waveB * 0.28 + waveC * 0.22 + waveD * 0.16;

      if (mix > 0.44) return ".";
      if (mix > 0.18) return ":";
      if (mix > -0.06) return "'";
      if (mix > -0.28) return "`";
      return ",";
    }

    function resetDynamicFields() {
      trailField.fill(0);
      for (let i = 0; i < glowField.length; i += 1) {
        glowField[i] = Math.max(0, glowField[i] - 0.022);
      }
      for (let i = 0; i < decayField.length; i += 1) {
        decayField[i] = Math.max(0, decayField[i] - 0.022);
        if (decayField[i] < 0.02) {
          charField[i] = " ";
        }
      }
    }

    function stampTrailPoint(px, py, power) {
      const gx = px / cellW;
      const gy = py / cellH;
      const radius = 1.2 + power * 2.0;
      const minX = clamp(Math.floor(gx - radius), 0, cols - 1);
      const maxX = clamp(Math.ceil(gx + radius), 0, cols - 1);
      const minY = clamp(Math.floor(gy - radius), 0, rows - 1);
      const maxY = clamp(Math.ceil(gy + radius), 0, rows - 1);
      const radiusSq = radius * radius;

      for (let y = minY; y <= maxY; y += 1) {
        for (let x = minX; x <= maxX; x += 1) {
          const dx = x - gx;
          const dy = y - gy;
          const d2 = dx * dx + dy * dy;
          if (d2 > radiusSq) continue;

          const distance = Math.sqrt(d2);
          const influence = (1 - distance / radius) * 0.95;
          const k = idx(x, y);
          trailField[k] = Math.max(trailField[k], influence);
          glowField[k] = Math.max(glowField[k], influence * 1.05);
          if (Math.random() < influence * 0.22) {
            charField[k] = choose(distance < radius * 0.4 ? nearSet : tailSet);
            decayField[k] = Math.max(decayField[k], influence * 1.35);
          }
        }
      }
    }

    function stampTrailLine(x1, y1, x2, y2) {
      const dx = x2 - x1;
      const dy = y2 - y1;
      const distance = Math.hypot(dx, dy);
      const steps = Math.max(1, Math.ceil(distance / 6));
      for (let step = 0; step <= steps; step += 1) {
        const t = step / steps;
        stampTrailPoint(x1 + dx * t, y1 + dy * t, 1);
      }
    }

    function renderFrame(timeMs) {
      if (destroyed) return;

      const time = timeMs * 0.001;
      renderFrame.lastTime = timeMs;
      if (!introStartTime) introStartTime = timeMs;
      resetDynamicFields();

      const introRaw = clamp((timeMs - introStartTime) / introDurationMs, 0, 1);
      const introProgress = easeOutCubic(introRaw);
      const introNoise = 1 - introProgress;
      const introTargetResolved = Math.floor(cols * rows * introProgress);
      resolveIntroCells(introTargetResolved);

      const pointerRecentlyActive = performance.now() - pointerActiveAt < 340;
      const trailActive = pointerDown || pointerRecentlyActive;
      if (trailActive && prevPointerX > -9990) {
        stampTrailLine(prevPointerX, prevPointerY, pointerX, pointerY);
      }

      ctx.clearRect(0, 0, width, height);

      const isDay = document.body.getAttribute("data-theme") === "day";
      const baseRgb = isDay ? [72, 112, 214] : [104, 170, 255];
      const edgeRgb = isDay ? [92, 138, 238] : [162, 211, 255];
      const trailRgb = isDay ? [118, 150, 248] : [236, 246, 255];

      for (let y = 0; y < rows; y += 1) {
        const py = y * cellH;
        for (let x = 0; x < cols; x += 1) {
          const px = x * cellW;
          const k = idx(x, y);

          const dx = x - cols / 2;
          const dy = y - rows / 2;
          const centerDist = Math.sqrt(dx * dx + dy * dy);
          const centerNorm = clamp(centerDist / (Math.max(cols, rows) * 0.7), 0, 1);
          const edgeBias = Math.pow(centerNorm, 1.18);
          const baseGlow = 0.28 + edgeBias * 0.22;
          const trailGlow = trailField[k];
          const storedGlow = glowField[k];
          const finalGlow = Math.max(baseGlow, trailGlow * 0.95, storedGlow * 0.9);

          let char = baseChar(x, y, time);
          if (charField[k] !== " " && decayField[k] > 0.02) {
            char = charField[k];
          } else if (introNoise > 0) {
            if (!introResolved[k]) {
              char = introField[k];
            }
          }

          let alpha = clamp(0.18 + finalGlow * 1.02, 0, 1);
          let rgb = baseRgb;
          if (edgeBias > 0.08) {
            rgb = edgeRgb;
          }
          if (storedGlow > 0.05) {
            rgb = trailRgb;
            alpha = clamp(alpha + storedGlow * 0.56, 0, 1);
          }
          if (introNoise > 0.02 && Math.random() < introNoise * 0.48) {
            rgb = trailRgb;
            alpha = clamp(alpha + introNoise * 0.32, 0, 1);
          }

          ctx.fillStyle = "rgba(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + "," + alpha.toFixed(3) + ")";
          ctx.fillText(char, px, py);
        }
      }

      prevPointerX = pointerX;
      prevPointerY = pointerY;
      rafId = window.requestAnimationFrame(renderFrame);
    }

    function updatePointerPosition(event) {
      const rect = scene.getBoundingClientRect();
      const nextX = event.clientX - rect.left;
      const nextY = event.clientY - rect.top;
      if (nextX < 0 || nextY < 0 || nextX > rect.width || nextY > rect.height) {
        return false;
      }
      pointerX = nextX;
      pointerY = nextY;
      pointerActiveAt = performance.now();
      if (prevPointerX < -9990) {
        prevPointerX = pointerX;
        prevPointerY = pointerY;
      }
      return true;
    }

    function handlePointerDown(event) {
      if (activePointerId !== null && event.pointerId !== activePointerId) return;
      activePointerId = event.pointerId;
      pointerDown = true;
      if (!updatePointerPosition(event)) return;
      stampTrailPoint(pointerX, pointerY, 1);
    }

    function handlePointerMove(event) {
      const isTouchPointer = event.pointerType === "touch";
      if (isTouchPointer && !pointerDown) return;
      if (activePointerId !== null && event.pointerId !== activePointerId) return;
      if (isTouchPointer) {
        activePointerId = event.pointerId;
      }
      if (!updatePointerPosition(event)) {
        return;
      }
    }

    function resetPointerState() {
      pointerDown = false;
      activePointerId = null;
      pointerX = -9999;
      pointerY = -9999;
      prevPointerX = -9999;
      prevPointerY = -9999;
    }

    function handlePointerLeave(event) {
      if (event.pointerType !== "mouse") return;
      resetPointerState();
    }

    function handlePointerUp(event) {
      if (activePointerId !== null && event.pointerId !== activePointerId) return;
      resetPointerState();
    }

    function handleResize() {
      setCanvasSize();
    }

    function destroy() {
      destroyed = true;
      if (rafId) window.cancelAnimationFrame(rafId);
      hero.removeEventListener("pointerdown", handlePointerDown);
      hero.removeEventListener("pointermove", handlePointerMove);
      hero.removeEventListener("pointerleave", handlePointerLeave);
      hero.removeEventListener("pointerup", handlePointerUp);
      hero.removeEventListener("pointercancel", handlePointerUp);
      window.removeEventListener("resize", handleResize);
    }

    setCanvasSize();
    fallback.hidden = true;
    hero.addEventListener("pointerdown", handlePointerDown, { passive: true });
    hero.addEventListener("pointermove", handlePointerMove, { passive: true });
    hero.addEventListener("pointerleave", handlePointerLeave, { passive: true });
    hero.addEventListener("pointerup", handlePointerUp, { passive: true });
    hero.addEventListener("pointercancel", handlePointerUp, { passive: true });
    window.addEventListener("resize", handleResize, { passive: true });
    window.addEventListener("pagehide", destroy, { once: true });
    rafId = window.requestAnimationFrame(renderFrame);
  }

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initAsciiScene, { once: true });
    } else {
      initAsciiScene();
    }
  } catch (error) {
    if (window.console && console.warn) {
      console.warn("home-v2 ascii scene disabled", error);
    }
  }
})();
