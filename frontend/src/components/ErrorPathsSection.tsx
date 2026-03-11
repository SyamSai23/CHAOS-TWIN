import { AlertTriangle } from "lucide-react";
import type { AnalysisErrorPath } from "../types";

type Props = {
  errorPaths: AnalysisErrorPath[];
};

export default function ErrorPathsSection({ errorPaths }: Props) {
  if (errorPaths.length === 0) return null;

  return (
    <div className="error-paths-section">
      <span className="error-paths-label">ERROR PATHS</span>
      <div className="error-paths-list">
        {errorPaths.map((ep, i) => (
          <div key={i} className="error-path-item">
            <AlertTriangle size={13} />
            <span className="error-path-detail">
              {ep.trigger}
              {ep.status_code && <span className="error-path-code">{ep.status_code}</span>}
            </span>
            {ep.message && <span className="error-path-message">{ep.message}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
