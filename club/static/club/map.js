// Wine region map: one circle per region the club has tasted from, sized by bottles
// and coloured by club average, plus small hollow dots for established regions not tasted
// yet. Clicking a marker loads its details panel with htmx.
(function () {
  const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const TILE_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  // OSM's tile policy blocks requests without a Referer, and Django's default
  // Referrer-Policy (same-origin) strips it, so send our origin with tile requests only.
  const TILE_REFERRER_POLICY = "strict-origin-when-cross-origin";
  const MAX_ZOOM = 12;
  const HOME_COUNTRY = "Australia";
  const HOME_BOUNDS = [[-44, 112], [-10, 154]];
  const WORLD_BOUNDS = [[-60, -180], [75, 180]];
  const FIT_PADDING = [24, 24];
  const MIN_RADIUS = 6;
  const RADIUS_PER_SQRT_BOTTLE = 3;
  const UNTASTED_RADIUS = 4;
  const PANEL_SELECTOR = "#region-panel";
  const UNTASTED_TOGGLE_ID = "show-untasted";
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
    const place = "<strong>" + escapeHtml(marker.name) + "</strong>, " + escapeHtml(marker.country);
    if (!marker.tasted) return place + "<br>not tasted yet";
    const average = marker.mean === null ? "not scored" : "avg " + marker.mean.toFixed(2);
    const bottles = marker.bottles + (marker.bottles === 1 ? " bottle" : " bottles");
    return place + "<br>" + bottles + " · " + average;
  }

  function tastedStyle(colour, surface) {
    return function (marker) {
      return {
        radius: MIN_RADIUS + RADIUS_PER_SQRT_BOTTLE * Math.sqrt(marker.bottles),
        color: surface,
        weight: 1.5,
        fillColor: colour(marker),
        fillOpacity: 0.85,
      };
    };
  }

  function untastedStyle(muted) {
    return function () {
      return { radius: UNTASTED_RADIUS, color: muted, weight: 1.5, fillOpacity: 0 };
    };
  }

  // Returns the layer holding untasted regions, so it can be toggled.
  function addMarkers(map, tasted, untasted) {
    const styleTasted = tastedStyle(colourFor(tasted), css("--surface"));
    const styleUntasted = untastedStyle(css("--muted"));
    const untastedLayer = L.featureGroup().addTo(map);
    const tastedLayer = L.layerGroup().addTo(map);
    let selected = null;

    function add(layer, style) {
      return function (marker) {
        const circle = L.circleMarker([marker.lat, marker.lng], style(marker)).addTo(layer);
        circle.bindTooltip(tooltip(marker), { direction: "top" });
        circle.on("click", function () {
          if (selected) selected.circle.setStyle(selected.style(selected.marker));
          circle.setStyle({ color: css("--text"), weight: 3 });
          selected = { circle: circle, style: style, marker: marker };
          showPanel(marker.url);
        });
      };
    }

    untasted.forEach(add(untastedLayer, styleUntasted));
    // Largest first, so small regions stay clickable on top of big neighbours.
    tasted.slice().sort(function (a, b) { return b.bottles - a.bottles; })
      .forEach(add(tastedLayer, styleTasted));
    return untastedLayer;
  }

  function bindUntastedToggle(map, layer) {
    const toggle = document.getElementById(UNTASTED_TOGGLE_ID);
    if (!toggle) return;
    toggle.addEventListener("change", function () {
      // Re-added layers draw on top; keep untasted dots under the tasted circles.
      if (toggle.checked) layer.addTo(map).bringToBack();
      else map.removeLayer(layer);
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
    L.tileLayer(TILE_URL, {
      maxZoom: MAX_ZOOM,
      attribution: TILE_ATTRIBUTION,
      referrerPolicy: TILE_REFERRER_POLICY,
    }).addTo(map);
    const tasted = markers.filter(function (m) { return m.tasted; });
    const untasted = markers.filter(function (m) { return !m.tasted; });
    bindUntastedToggle(map, addMarkers(map, tasted, untasted));
    bindViewTabs(map, tasted);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
