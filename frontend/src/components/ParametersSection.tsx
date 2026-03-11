import type { AnalysisParameter } from "../types";

type Props = {
  parameters: AnalysisParameter[];
};

export default function ParametersSection({ parameters }: Props) {
  if (parameters.length === 0) return null;

  return (
    <div className="params-section">
      <span className="params-label">PARAMETERS</span>
      <div className="params-list">
        {parameters.map((p, i) => (
          <div key={i} className="params-item">
            <code className="params-name">{p.name}</code>
            <span className="params-type">{p.type || "any"}</span>
            <span className="params-source">{p.source}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
