type Props = {
  mode: "story" | "technical";
  onChange: (mode: "story" | "technical") => void;
};

export default function ModeToggle({ mode, onChange }: Props) {
  return (
    <div className="mode-toggle">
      <button
        className={`mode-toggle-btn${mode === "story" ? " active" : ""}`}
        onClick={() => onChange("story")}
      >
        Overview
      </button>
      <button
        className={`mode-toggle-btn${mode === "technical" ? " active" : ""}`}
        onClick={() => onChange("technical")}
      >
        Sequence
      </button>
    </div>
  );
}
