// Wine region map: one circle per region the club has tasted from, sized by bottles
// and coloured by club average. Clicking a circle loads its details panel with htmx.
(function () {
  const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const TILE_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const MAX_ZOOM = 12;
  const HOME_COUNTRY = "Australia";
  const HOME_BOUNDS = [[-44, 112], [-10, 154]];
  const WORLD_BOUNDS = [[-60, -180], [75, 180]];
  const FIT_PADDING = [24, 24];
  const MIN_RADIUS = 6;
  const RADIUS_PER_SQRT_BOTTLE = 3;
  const PANEL_SELECTOR = "#region-panel";
  const NARROW_SCREEN = "(max-width: 860px)";

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function hexToRgb(hex) {
    const value = parseInt(hex.replace("#", ""), 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
  }

  // Blend from the low-score colour to the high-score colour (0 <= t <= 1).
  function scoreColour(low, high, t) {
    const a = hexToRgb(low);
    const b = hexToRgb(high);
    const mixed = a.map(function (channel, i) { return Math.round(channel + (b[i] - channel) * t); });
    return "rgb(" + mixed.join(",") + ")";
  }

  // Colour by rank rather than raw value: regional averages bunch closely together.
  function colourFor(markers) {
    const means = markers
      .map(function (m) { return m.mean; })
      .filter(function (m) { return m !== null; })
      .sort(function (a, b) { return a - b; });
    const steps = Math.max(means.length - 1, 1);
    const low = css("--chart-2");
    const high = css("--chart-1");
    const unscored = css("--muted");
    return function (marker) {
      if (marker.mean === null) return unscored;
      return scoreColour(low, high, means.indexOf(marker.mean) / steps);
    };
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function tooltip(marker) {
    const average = marker.mean === null ? "not scored" : "avg " + marker.mean.toFixed(2);
    const bottles = marker.bottles + (marker.bottles === 1 ? " bottle" : " bottles");
    return "<strong>" + escapeHtml(marker.name) + "</strong>, " + escapeHtml(marker.country) +
      "<br>" + bottles + " · " + average;
  }

  function addMarkers(map, markers) {
    const colour = colourFor(markers);
    const surface = css("--surface");
    let selected = null;
    // Largest first, so small regions stay clickable on top of big neighbours.
    markers.slice().sort(function (a, b) { return b.bottles - a.bottles; }).forEach(function (marker) {
      const circle = L.circleMarker([marker.lat, marker.lng], {
        radius: MIN_RADIUS + RADIUS_PER_SQRT_BOTTLE * Math.sqrt(marker.bottles),
        color: surface,
        weight: 1.5,
        fillColor: colour(marker),
        fillOpacity: 0.85,
      }).addTo(map);
      circle.bindTooltip(tooltip(marker), { direction: "top" });
      circle.on("click", function () {
        if (selected) selected.setStyle({ color: surface, weight: 1.5 });
        circle.setStyle({ color: css("--text"), weight: 3 });
        selected = circle;
        showPanel(marker.url);
      });
    });
  }

  function showPanel(url) {
    htmx.ajax("GET", url, { target: PANEL_SELECTOR, swap: "innerHTML" }).then(function () {
      if (window.matchMedia(NARROW_SCREEN).matches) {
        document.querySelector(PANEL_SELECTOR).scrollIntoView({ behavior: "smooth" });
      }
    });
  }

  function bindViewTabs(map, markers) {
    const tabs = document.querySelectorAll("#map-views a");
    function fitTo(list, fallback) {
      if (!list.length) return map.fitBounds(fallback);
      map.fitBounds(list.map(function (m) { return [m.lat, m.lng]; }), { padding: FIT_PADDING });
    }
    const home = markers.filter(function (m) { return m.country === HOME_COUNTRY; });
    const views = {
      australia: function () { fitTo(home, HOME_BOUNDS); },
      world: function () { fitTo(markers, WORLD_BOUNDS); },
    };
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function (event) {
        event.preventDefault();
        tabs.forEach(function (other) { other.classList.toggle("active", other === tab); });
        views[tab.dataset.view]();
      });
    });
    views.australia();
  }

  function init() {
    const element = document.getElementById("region-map");
    if (!element || !window.L) return;
    const source = document.getElementById(element.dataset.markers);
    const markers = source ? JSON.parse(source.textContent) : [];
    const map = L.map(element, { worldCopyJump: true });
    L.tileLayer(TILE_URL, { maxZoom: MAX_ZOOM, attribution: TILE_ATTRIBUTION }).addTo(map);
    addMarkers(map, markers);
    bindViewTabs(map, markers);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
