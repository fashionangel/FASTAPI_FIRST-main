/* Капча «Чекбокс-непоседа» */
(function () {
  const API_NEW = "/krivo-captcha/new";
  const API_ANSWER = "/krivo-captcha/answer";
  const DODGE_DIST = 70;      // на таком расстоянии курсора чекбокс паникует
  const DODGE_THROTTLE = 420; // мс между "промахами" на клиенте

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function initWidget(root) {
    const hidden = root.querySelector('input[name="captcha_token"]');
    const titleEl = root.querySelector(".krivo-title");
    const stepEl = root.querySelector(".krivo-step");
    const msgEl = root.querySelector(".krivo-msg");
    const stageEl = root.querySelector(".krivo-stage");

    let box, chip, gloat = false, lastDodge = 0;
    const PUFFS = ["💨", "🫠", "🤡"];

    function say(text, cls) {
      msgEl.textContent = text || "";
      msgEl.className = "krivo-msg" + (cls ? " " + cls : "");
    }

    async function api(url, body) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      return res.json();
    }

    function handle(d) {
      if (d && d.done) return renderDone(d);
      if (d && d.ok && d.stage === "gloat") return renderGloat(d);
      if (d && d.ok && d.taunt) { say(d.taunt + " " + (d.sticker || ""), "bad"); return; }
      if (d && d.restart) {
        say(d.error, "bad");
        setTimeout(() => api(API_NEW).then(renderStart), 1400);
        return;
      }
      say((d && d.error) || "Чекбокс молчит. Зловеще.", "bad");
    }

    function renderStart(d) {
      gloat = false;
      hidden.value = "";
      titleEl.textContent = d.title;
      stepEl.textContent = "погоня 1 из 1";
      say("");
      stageEl.innerHTML = "";
      stageEl.appendChild(el("div", "krivo-sub", d.text));
      box = el("div", "krivo-check-box");
      chip = el("div", "krivo-check", "☑ Я не робот");
      box.appendChild(chip);
      stageEl.appendChild(box);

      chip.style.left = Math.max(8, box.clientWidth * 0.1) + "px";
      chip.style.top = Math.max(8, box.clientHeight * 0.38) + "px";

      box.addEventListener("mousemove", onMove);
      chip.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!gloat) dodge(e);   // в зазнавшемся режиме чекбокс стоит смирно и ловится
      });
      chip.addEventListener("click", () => {
        if (!gloat) return;
        api(API_ANSWER, { action: "caught" }).then(handle);
      });
    }

    function onMove(e) {
      if (gloat || !chip) return;
      const r = box.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const cx = chip.offsetLeft + chip.offsetWidth / 2;
      const cy = chip.offsetTop + chip.offsetHeight / 2;
      if (Math.hypot(cx - mx, cy - my) < DODGE_DIST) dodge(e);
    }

    function dodge(e) {
      const now = Date.now();
      if (now - lastDodge < DODGE_THROTTLE) return;
      lastDodge = now;

      const oldX = chip.offsetLeft, oldY = chip.offsetTop;
      spawnSticker(oldX, oldY);

      const r = box.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      let nx, ny, guard = 0;
      do {
        nx = Math.random() * Math.max(1, box.clientWidth - chip.offsetWidth);
        ny = Math.random() * Math.max(1, box.clientHeight - chip.offsetHeight);
        guard++;
      } while (
        Math.hypot(nx + chip.offsetWidth / 2 - mx, ny + chip.offsetHeight / 2 - my) < 110 &&
        guard < 20
      );
      chip.style.left = nx + "px";
      chip.style.top = ny + "px";

      api(API_ANSWER, { action: "miss" }).then(handle);
    }

    function spawnSticker(x, y) {
      const s = el("span", "krivo-sticker", PUFFS[Math.floor(Math.random() * PUFFS.length)]);
      s.style.left = x + "px";
      s.style.top = y + "px";
      box.appendChild(s);
      setTimeout(() => s.remove(), 950);
    }

    function renderGloat(d) {
      gloat = true;
      say(d.taunt + " " + (d.sticker || ""), "good");
      chip.textContent = "☑ Я не робот 😏";
      chip.classList.add("krivo-check-gloat");
      requestAnimationFrame(() => {
        chip.style.left = Math.max(8, (box.clientWidth - chip.offsetWidth) / 2) + "px";
        chip.style.top = Math.max(8, (box.clientHeight - chip.offsetHeight) / 2) + "px";
      });
    }

    function renderDone(d) {
      hidden.value = d.token;
      titleEl.textContent = "Пройдено ✔";
      stepEl.textContent = "галочка поставлена";
      say("");
      if (chip) chip.textContent = "☑ Спасибо ❤️";
      stageEl.appendChild(el("div", "krivo-done", d.success_text));
    }

    // не даём отправить форму без галочки человечности
    const form = root.closest("form");
    if (form) {
      form.addEventListener("submit", (e) => {
        if (!hidden.value) {
          e.preventDefault();
          say("Чекбокс ещё не пойман. Он где-то здесь. Он ждёт.", "bad");
        }
      });
    }

    api(API_NEW).then(renderStart);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-krivo-captcha]").forEach(initWidget);
  });
})();