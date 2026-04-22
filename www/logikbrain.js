frappe.ready(function () {
    const input       = document.getElementById("logikbrain-input");
    const askBtn      = document.getElementById("logikbrain-ask-btn");
    const spinner     = document.getElementById("logikbrain-spinner");
    const card        = document.getElementById("logikbrain-card");
    const chartDiv    = document.getElementById("logikbrain-chart");
    const titleEl     = document.getElementById("logikbrain-chart-title");
    const rowsEl      = document.getElementById("logikbrain-row-count");
    const tableWrap   = document.getElementById("logikbrain-table-wrap");
    const explanation = document.getElementById("logikbrain-explanation");
    const expText     = document.getElementById("logikbrain-explanation-text");

    let chartInstance = null;
    let currentCurrency = "";

    const PALETTE = ["#5b8dee", "#eb6f92", "#56c596", "#f4a44a", "#a17cf4", "#38bdf8", "#f87171", "#34d399"];

    function setLoading(loading) {
        askBtn.disabled = loading;
        spinner.classList.toggle("active", loading);
    }

    function ask() {
        const question = input.value.trim();
        if (!question) return;
        setLoading(true);

        frappe.call({
            method: "erp_overrides.www.api.ask_logikmind",
            args: { question },
            callback: function (r) {
                setLoading(false);
                if (r.message) renderChart(question, r.message);
            },
            error: function (err) {
                setLoading(false);
                frappe.msgprint({
                    title: __("Logikbrain Error"),
                    message: __("Failed to get a response. Please try again."),
                    indicator: "red",
                });
                console.error("logikbrain api error", err);
            },
        });
    }

    function fmt(val, withCurrency) {
        if (typeof val !== "number") return val;
        const prefix = (withCurrency && currentCurrency) ? currentCurrency + " " : "";
        if (Math.abs(val) >= 1e6) return prefix + (val / 1e6).toFixed(2) + "M";
        if (Math.abs(val) >= 1e3) return prefix + (val / 1e3).toFixed(1) + "K";
        return prefix + val.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    function buildChartOption(response) {
        const { chart_type, title, x_field, y_field, data, series } = response;

        const baseTitle = {
            show: false  // title is rendered in the card header, not inside echarts
        };

        const baseTooltip = {
            backgroundColor: "#1e293b",
            borderColor: "#1e293b",
            textStyle: { color: "#f8fafc", fontSize: 13 },
            padding: [8, 12],
        };

        if (chart_type === "grouped_bar") {
            const xValues = data.map(row => row[x_field]);
            return {
                title: baseTitle,
                tooltip: {
                    ...baseTooltip,
                    trigger: "axis",
                    axisPointer: { type: "shadow" },
                    formatter: (params) =>
                        `<span style="color:#94a3b8;font-size:12px">${params[0].name}</span><br/>` +
                        params.map(p => `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${p.color};margin-right:5px"></span>${p.seriesName}: <b>${fmt(p.value, true)}</b>`).join("<br/>"),
                },
                legend: {
                    data: series.map(s => s.label),
                    bottom: 8,
                    textStyle: { color: "#64748b", fontSize: 12 },
                },
                grid: { left: 16, right: 16, bottom: 40, top: 16, containLabel: true },
                xAxis: {
                    type: "category",
                    data: xValues,
                    axisLine: { lineStyle: { color: "#e2e8f0" } },
                    axisTick: { show: false },
                    axisLabel: { rotate: 30, overflow: "truncate", width: 110, color: "#64748b", fontSize: 12 },
                },
                yAxis: {
                    type: "value",
                    splitLine: { lineStyle: { color: "#f1f5f9", type: "dashed" } },
                    axisLine: { show: false },
                    axisTick: { show: false },
                    axisLabel: { color: "#94a3b8", fontSize: 11, formatter: (v) => fmt(v, true) },
                },
                series: series.map((s, i) => ({
                    name: s.label,
                    type: "bar",
                    data: data.map(row => row[s.field]),
                    barMaxWidth: 36,
                    barMinHeight: 2,
                    itemStyle: { color: PALETTE[i], borderRadius: [4, 4, 0, 0] },
                    emphasis: { itemStyle: { opacity: 0.85 } },
                })),
            };
        }

        if (chart_type === "pie" || chart_type === "donut") {
            const seriesData = data.map((row, i) => ({
                name: row[x_field],
                value: row[y_field],
                itemStyle: { color: PALETTE[i % PALETTE.length] },
            }));

            return {
                title: baseTitle,
                tooltip: {
                    ...baseTooltip,
                    trigger: "item",
                    formatter: (p) => `${p.name}<br/><b>${fmt(p.value, true)}</b> (${p.percent}%)`,
                },
                legend: {
                    orient: "horizontal",
                    bottom: 8,
                    textStyle: { color: "#64748b", fontSize: 12 },
                    icon: "circle",
                },
                series: [{
                    type: "pie",
                    radius: chart_type === "donut" ? ["42%", "68%"] : "62%",
                    center: ["50%", "46%"],
                    data: seriesData,
                    label: { show: true, formatter: "{b}\n{d}%", fontSize: 12, color: "#475569" },
                    labelLine: { lineStyle: { color: "#cbd5e1" } },
                    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,.2)" } },
                }],
            };
        }

        // bar or line
        const xValues = data.map((row) => row[x_field]);
        const yValues = data.map((row) => row[y_field]);
        const isLine  = chart_type === "line";

        return {
            title: baseTitle,
            tooltip: {
                ...baseTooltip,
                trigger: "axis",
                axisPointer: { type: isLine ? "line" : "shadow", shadowStyle: { color: "rgba(91,141,238,.08)" } },
                formatter: (params) => {
                    const p = params[0];
                    return `<span style="color:#94a3b8;font-size:12px">${p.name}</span><br/><b>${fmt(p.value, true)}</b>`;
                },
            },
            grid: { left: 16, right: 16, bottom: 12, top: 32, containLabel: true },
            xAxis: {
                type: "category",
                data: xValues,
                axisLine: { lineStyle: { color: "#e2e8f0" } },
                axisTick: { show: false },
                axisLabel: {
                    rotate: xValues.length > 6 ? 30 : 0,
                    overflow: "truncate",
                    width: 110,
                    color: "#64748b",
                    fontSize: 12,
                },
            },
            yAxis: {
                type: "value",
                splitLine: { lineStyle: { color: "#f1f5f9", type: "dashed" } },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: "#94a3b8", fontSize: 11, formatter: (v) => fmt(v, true) },
            },
            series: [{
                type: isLine ? "line" : "bar",
                data: yValues,
                smooth: isLine,
                symbol: isLine ? "circle" : "none",
                symbolSize: 6,
                barMaxWidth: 52,
                barMinHeight: 2,
                itemStyle: {
                    color: isLine ? "#5b8dee" : {
                        type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: "#5b8dee" },
                            { offset: 1, color: "#93b8f5" },
                        ],
                    },
                    borderRadius: isLine ? 0 : [4, 4, 0, 0],
                },
                lineStyle: { color: "#5b8dee", width: 2.5 },
                areaStyle: isLine ? {
                    color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [{ offset: 0, color: "rgba(91,141,238,.25)" }, { offset: 1, color: "rgba(91,141,238,0)" }] }
                } : undefined,
                emphasis: { itemStyle: { color: "#4073d6" } },
            }],
        };
    }

    function renderTable(data) {
        if (!data || !data.length) { tableWrap.innerHTML = ""; return; }

        const keys = Object.keys(data[0]);
        const isNumeric = (v) => typeof v === "number" || (typeof v === "string" && v !== "" && !isNaN(Number(v)));

        const head = keys.map(k =>
            `<th>${k.replace(/_/g, " ")}</th>`
        ).join("");

        const rows = data.map(row =>
            "<tr>" + keys.map(k => {
                const v = row[k];
                const numeric = isNumeric(v);
                const display = numeric ? fmt(Number(v)) : (v ?? "—");
                return `<td class="${numeric ? "num" : ""}">${display}</td>`;
            }).join("") + "</tr>"
        ).join("");

        tableWrap.innerHTML = `<table class="lm-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
    }

    function fetchExplanation(question, data) {
        expText.innerHTML = `<span class="lm-exp-spinner">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg> Analysing…</span>`;
        explanation.classList.add("active");

        frappe.call({
            method: "erp_overrides.www.api.explain_logikmind",
            args: { question, data: JSON.stringify(data) },
            callback: function (r) {
                const exp = ((r.message || {}).explanation || "").trim();
                if (exp) {
                    expText.textContent = exp;
                } else {
                    explanation.classList.remove("active");
                }
            },
            error: function () {
                explanation.classList.remove("active");
            },
        });
    }

    function renderChart(question, response) {
        currentCurrency = response.currency || "";
        card.classList.add("active");
        titleEl.textContent = response.title || "";
        rowsEl.textContent  = (currentCurrency ? currentCurrency + " · " : "") + response.data.length + " results";

        if (chartInstance) chartInstance.dispose();
        chartInstance = echarts.init(chartDiv, null, { renderer: "svg" });
        chartInstance.setOption(buildChartOption(response));

        renderTable(response.data);
        fetchExplanation(question, response.data);

        window.addEventListener("resize", () => chartInstance && chartInstance.resize());
    }

    document.getElementById("logikbrain-print-btn").addEventListener("click", function () {
        const title      = titleEl.textContent || "Logikbrain";
        const rowCount   = document.getElementById("logikbrain-row-count").textContent || "";
        const svgEl      = chartDiv.querySelector("svg");
        const chartHtml  = svgEl ? `<div class="chart-wrap">${svgEl.outerHTML}</div>` : "";
        const tableHtml  = tableWrap.innerHTML;
        const insightTxt = expText && explanation.classList.contains("active") ? expText.textContent.trim() : "";
        const insightHtml = insightTxt
            ? `<div class="insight-box"><span class="insight-label">Insight</span><p class="insight-body">${insightTxt}</p></div>`
            : "";

        const win = window.open("", "_blank");
        win.document.write(`<!DOCTYPE html>
<html><head><title>${title}</title><style>
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;color:#1e293b}
  .card-header{padding:20px 28px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e2e8f0}
  .card-title{font-size:15px;font-weight:600;margin:0;color:#1e293b}
  .card-rows{font-size:12px;color:#94a3b8}
  .chart-wrap{display:block;position:relative;overflow:hidden;width:100%;height:400px;padding:16px 28px 8px}
  .chart-wrap svg{position:relative;display:block;width:100%;height:100%}
  .insight-box{display:block;position:relative;margin:12px 28px 16px;padding:12px 16px;background:#f8fafc;border-left:3px solid #5b8dee;border-radius:4px}
  .insight-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;display:block;margin-bottom:4px}
  .insight-body{margin:0;font-size:13px;color:#334155;line-height:1.6}
  .table-wrap{display:block;position:relative;padding:0 28px 24px}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}
  th{background:#f8fafc;color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:9px 12px;text-align:left;border-bottom:1px solid #e2e8f0;white-space:nowrap}
  td{padding:8px 12px;border-bottom:1px solid #f1f5f9;color:#334155;white-space:nowrap}
  td.num{text-align:right;font-weight:500;color:#1e293b}
  @media print{@page{margin:1cm}}
</style></head><body>
<div class="card-header">
  <p class="card-title">${title}</p>
  <span class="card-rows">${rowCount}</span>
</div>
${chartHtml}
${insightHtml}
<div class="table-wrap">${tableHtml}</div>
<script>window.onload=function(){window.print();window.close()}<\/script>
</body></html>`);
        win.document.close();
    });

    askBtn.addEventListener("click", ask);
    input.addEventListener("keydown", (e) => e.key === "Enter" && ask());
});
