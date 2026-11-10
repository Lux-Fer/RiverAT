/* RiverAT custom select: native select stays for form submission, menu is rendered. */
(() => {
  const instances = [];
  const NS = "http://www.w3.org/2000/svg";

  const icon = (path, className) => {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", className);
    const shape = document.createElementNS(NS, "path");
    shape.setAttribute("d", path);
    svg.append(shape);
    return svg;
  };

  const closeAll = (except) => {
    instances.forEach((item) => {
      if (item.root !== except) item.close();
    });
  };

  const enhance = (root, index) => {
    if (root.classList.contains("is-enhanced")) return;
    const native = root.querySelector(":scope > select");
    if (!native || native.options.length === 0) return;

    root.classList.add("is-enhanced");
    const required = native.required;
    if (required) {
      root.dataset.required = "true";
      native.required = false;
    }
    native.tabIndex = -1;
    native.setAttribute("aria-hidden", "true");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "ui-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");

    const menuId = `ui-select-menu-${index}`;
    trigger.setAttribute("aria-controls", menuId);
    const value = document.createElement("span");
    value.className = "ui-select-value";
    trigger.append(value, icon("m6 9 6 6 6-6", "caret"));

    const menu = document.createElement("div");
    menu.className = "ui-select-menu";
    menu.id = menuId;
    menu.setAttribute("role", "listbox");
    menu.hidden = true;

    const context = root.closest("label, .ui-field, .brief-row, .audit-filter");
    const label = context?.querySelector(".k, .brief-label")?.textContent
      || native.getAttribute("aria-label")
      || native.name;
    trigger.setAttribute("aria-label", label.replace(/\s+/g, " ").trim());

    const optionButtons = Array.from(native.options).map((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ui-select-option";
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", option.selected ? "true" : "false");
      button.dataset.value = option.value;
      button.disabled = option.disabled;

      const text = document.createElement("span");
      text.textContent = option.textContent.trim() || option.value;
      button.append(text, icon("M20 6 9 17l-5-5", "check"));
      return button;
    });
    menu.append(...optionButtons);
    root.append(trigger, menu);

    const sync = () => {
      const selected = Array.from(native.options).find((option) => option.selected);
      value.textContent = selected?.textContent.trim() || native.options[0]?.textContent.trim() || "";
      optionButtons.forEach((button, i) => {
        button.setAttribute(
          "aria-selected",
          native.options[i]?.selected ? "true" : "false",
        );
      });
      root.classList.remove("is-invalid");
      trigger.removeAttribute("aria-invalid");
    };

    const close = () => {
      root.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
      menu.hidden = true;
    };

    const enabled = () => optionButtons.filter((button) => !button.disabled);

    const open = () => {
      if (native.disabled) return;
      closeAll(root);
      root.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      menu.hidden = false;
      const selected = optionButtons.find(
        (button) => button.getAttribute("aria-selected") === "true" && !button.disabled,
      );
      (selected || enabled()[0])?.focus();
    };

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      if (root.classList.contains("is-open")) close();
      else open();
    });

    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault();
        open();
      } else if (event.key === "Escape") {
        close();
      }
    });

    optionButtons.forEach((button, i) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (button.disabled) return;
        native.value = button.dataset.value;
        native.dispatchEvent(new Event("change", { bubbles: true }));
        close();
        trigger.focus();
      });

      button.addEventListener("keydown", (event) => {
        const list = enabled();
        const position = list.indexOf(button);
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          button.click();
        } else if (event.key === "Escape") {
          close();
          trigger.focus();
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          list[(position + 1) % list.length]?.focus();
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          list[(position - 1 + list.length) % list.length]?.focus();
        } else if (event.key === "Home") {
          event.preventDefault();
          list[0]?.focus();
        } else if (event.key === "End") {
          event.preventDefault();
          list[list.length - 1]?.focus();
        } else if (event.key === "Tab") {
          close();
        }
      });
    });

    native.addEventListener("change", sync);
    if (native.form) {
      native.form.addEventListener("reset", () => setTimeout(sync, 0));
      if (required) {
        native.form.addEventListener("submit", (event) => {
          if (!native.value) {
            event.preventDefault();
            root.classList.add("is-invalid");
            trigger.setAttribute("aria-invalid", "true");
            trigger.focus();
          }
        });
      }
    }

    if (native.disabled) {
      root.classList.add("is-disabled");
      trigger.disabled = true;
    }

    sync();
    instances.push({ root, close });
  };

  const boot = () => {
    document.querySelectorAll(".ui-select > select").forEach((native, index) => {
      enhance(native.parentElement, index);
    });
  };

  document.addEventListener("click", (event) => {
    instances.forEach((item) => {
      if (!item.root.contains(event.target)) item.close();
    });
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
