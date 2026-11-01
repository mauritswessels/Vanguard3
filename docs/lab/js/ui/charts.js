/* UI layer · Chart.js wrappers in the lab's dark theme. */
(function () {
  "use strict";
  const V3 = window.V3;
  const Chart = window.Chart;
  const GRID = "rgba(236,222,190,0.08)", TICK = "#8f897b";

  if (Chart) {
    Chart.defaults.color = TICK;
    Chart.defaults.font.family = '"Inter", ui-sans-serif, system-ui, sans-serif';
    Chart.defaults.font.size = 10;
    Chart.defaults.animation = false;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = "rgba(14,13,10,.95)";
    Chart.defaults.plugins.tooltip.borderColor = "rgba(236,222,190,.25)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.elements.point.radius = 0;
    Chart.defaults.elements.line.borderWidth = 1.5;
  }

  /** Chart.js needs a sized, relatively positioned parent. */
  function host(canvas) {
    if (canvas.parentElement.dataset.host) return canvas;
    const d = document.createElement("div"); d.dataset.host = "1";
    d.style.cssText = "position:relative;flex:1;min-height:0;width:100%";
    canvas.replaceWith(d); d.appendChild(canvas);
    return canvas;
  }

  function scales({ yFmt, xTicks = 6, yMin, yMax, category = true } = {}) {
    return {
      x: { type: category ? "category" : "linear", grid: { color: GRID, drawTicks: false }, border: { display: false },
        ticks: { maxTicksLimit: xTicks, maxRotation: 0, autoSkipPadding: 12 } },
      y: { grid: { color: GRID, drawTicks: false }, border: { display: false }, min: yMin, max: yMax,
        ticks: { maxTicksLimit: 5, padding: 6, callback: yFmt || (v => v) } },
    };
  }

  function gradient(ctx, color) {
    const { chartArea } = ctx.chart; if (!chartArea) return color + "22";
    const g = ctx.chart.ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    g.addColorStop(0, color + "40"); g.addColorStop(1, color + "00"); return g;
  }

  V3.charts = {
    line(canvas, { color = "#6fa3e8", fill = true, yFmt, label = "", zero = false, extra = [] } = {}) {
      return new Chart(host(canvas), {
        type: "line",
        data: { labels: [], datasets: [{ label, data: [], borderColor: color, fill: fill ? "origin" : false,
          backgroundColor: c => gradient(c, color), tension: 0.25 }, ...extra] },
        options: { scales: scales({ yFmt }), interaction: { mode: "index", intersect: false },
          plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label || ""} ${yFmt ? yFmt(c.parsed.y) : c.parsed.y}` } } },
          ...(zero ? {} : {}) },
      });
    },

    bars(canvas, { yFmt, label = "" } = {}) {
      return new Chart(host(canvas), {
        type: "bar",
        data: { labels: [], datasets: [{ label, data: [], backgroundColor: [], borderRadius: 1, barPercentage: 1, categoryPercentage: 0.9 }] },
        options: { scales: scales({ yFmt }), plugins: { tooltip: { callbacks: { label: c => `${label} ${yFmt ? yFmt(c.parsed.y) : c.parsed.y}` } } } },
      });
    },

    /** Replace the data of a single-series chart. */
    set(chart, labels, values, colors) {
      chart.data.labels = labels;
      chart.data.datasets[0].data = values;
      if (colors) chart.data.datasets[0].backgroundColor = colors;
      chart.update("none");
    },
  };
})();
