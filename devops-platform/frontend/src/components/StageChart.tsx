import type { ChartOptions } from "chart.js";
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from "chart.js";
import { Bar } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

type Props = {
  labels: string[];
  values: number[];
  status?: string;
};

const STAGE_COLORS = {
  pass:    "rgba(46, 125, 50, 0.85)",
  partial: "rgba(232, 131, 42, 0.85)",
  fail:    "rgba(198, 40, 40, 0.8)",
  empty:   "rgba(180, 166, 150, 0.3)",
};

const STAGE_BORDER = {
  pass:    "rgba(46, 125, 50, 1)",
  partial: "rgba(232, 131, 42, 1)",
  fail:    "rgba(198, 40, 40, 1)",
  empty:   "rgba(180, 166, 150, 0.5)",
};

export default function StageChart({ labels, values, status }: Props) {
  const bgColors = values.map((v) => {
    if (v >= 0.9) return STAGE_COLORS.pass;
    if (v >= 0.5) return STAGE_COLORS.partial;
    if (v > 0)    return STAGE_COLORS.fail;
    return STAGE_COLORS.empty;
  });

  const borderColors = values.map((v) => {
    if (v >= 0.9) return STAGE_BORDER.pass;
    if (v >= 0.5) return STAGE_BORDER.partial;
    if (v > 0)    return STAGE_BORDER.fail;
    return STAGE_BORDER.empty;
  });

  const data = {
    labels,
    datasets: [
      {
        label: "Stage Completion",
        data: values,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 2,
        borderRadius: 8,
        borderSkipped: false,
      },
    ],
  };

  const options: ChartOptions<"bar"> = {
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
      legend: { display: false },
      title: {
        display: false,
      },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const v = ctx.parsed.y;
            if (v >= 0.9) return " ✓ Passed";
            if (v >= 0.5) return " ~ Partial";
            if (v > 0)    return " ✗ Failed";
            return " — Pending";
          },
        },
        backgroundColor: "rgba(26, 18, 8, 0.85)",
        titleColor: "#f5efe6",
        bodyColor: "#f5efe6",
        padding: 10,
        borderRadius: 8,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          color: "#7a6b5a",
          font: { size: 11, weight: "700" as const },
        },
        border: { color: "rgba(0,0,0,0.06)" },
      },
      y: {
        beginAtZero: true,
        max: 1.2,
        grid: { color: "rgba(0,0,0,0.05)" },
        ticks: {
          display: false,
        },
        border: { display: false },
      },
    },
    animation: {
      duration: 600,
      easing: "easeOutQuart",
    },
  };

  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.25rem" }}>
        <div className="card-header" style={{ marginBottom: 0 }}>
          <div className="card-header-icon">📊</div>
          <div>
            <h2 className="card-title">Stage Progress</h2>
            <p style={{ fontSize: "0.7rem", color: "#9a8878", marginTop: "1px" }}>Completion status per pipeline stage</p>
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: "flex", gap: "1rem" }}>
          {[
            { color: STAGE_COLORS.pass, label: "Passed" },
            { color: STAGE_COLORS.partial, label: "Running" },
            { color: STAGE_COLORS.fail, label: "Failed" },
            { color: STAGE_COLORS.empty, label: "Pending" },
          ].map(({ color, label }) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
              <div style={{ width: "10px", height: "10px", borderRadius: "2px", background: color }} />
              <span style={{ fontSize: "0.68rem", color: "#9a8878", fontWeight: 600 }}>{label}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ height: "180px" }}>
        <Bar data={data} options={{ ...options, maintainAspectRatio: false }} />
      </div>
    </div>
  );
}
