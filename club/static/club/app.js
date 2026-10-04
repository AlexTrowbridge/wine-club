// Renders every <canvas data-chart="json-script-id"> with Chart.js, using the
// page's CSS colour tokens so charts follow the light/dark theme.
(function () {
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function render(canvas) {
    if (canvas._chart || !window.Chart) return;
    const source = document.getElementById(canvas.dataset.chart);
    if (!source) return;
    const config = JSON.parse(source.textContent);
    const palette = [css("--chart-1"), css("--chart-2")];
    const text = css("--muted");
    const grid = css("--border");

    Chart.defaults.color = text;
    Chart.defaults.borderColor = grid;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

    config.data.datasets.forEach(function (ds, i) {
      const colour = palette[i % palette.length];
      ds.borderColor = ds.borderColor || colour;
      ds.backgroundColor = ds.backgroundColor || (config.type === "bar" ? colour : colour + "99");
      if (ds.borderWidth === undefined) ds.borderWidth = config.type === "bar" ? 0 : 2;
    });

    config.options = config.options || {};
    config.options.responsive = true;
    config.options.maintainAspectRatio = false;
    config.options.plugins = config.options.plugins || {};

    // Optional per-bar counts ("n = 3") and point labels (wine names) in tooltips.
    const counts = config.counts;
    delete config.counts;
    config.options.plugins.tooltip = {
      callbacks: {
        afterLabel: function (ctx) {
          if (counts) return "n = " + counts[ctx.dataIndex];
          const raw = ctx.raw || {};
          return raw.label || "";
        },
      },
    };
    canvas._chart = new Chart(canvas, config);
  }

  function renderAll(root) {
    (root || document).querySelectorAll("canvas[data-chart]").forEach(render);
  }

  document.addEventListener("DOMContentLoaded", function () { renderAll(); });
  document.addEventListener("htmx:afterSwap", function (e) { renderAll(e.target); });

  // Show server-side errors (invalid score, scoring closed...) from htmx requests.
  document.addEventListener("htmx:responseError", function (e) {
    let toast = document.getElementById("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      toast.setAttribute("role", "alert");
      document.body.appendChild(toast);
    }
    toast.textContent = e.detail.xhr.responseText || "Something went wrong";
    toast.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () { toast.hidden = true; }, 4000);
  });

  // CSRF token for every htmx request.
  document.addEventListener("htmx:configRequest", function (e) {
    const token = document.querySelector("meta[name=csrf-token]");
    if (token) e.detail.headers["X-CSRFToken"] = token.content;
  });
})();
