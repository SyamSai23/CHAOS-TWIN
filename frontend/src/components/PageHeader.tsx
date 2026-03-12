import type { ReactNode } from "react";

type Props = {
  eyebrow?: string;
  title: string;
  description?: string | null;
  meta?: ReactNode;
  actions?: ReactNode;
};

export default function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
}: Props) {
  return (
    <div className="page-header">
      <div className="page-header-copy">
        {eyebrow ? <div className="page-eyebrow">{eyebrow}</div> : null}
        <div className="page-title-row">
          <h1 className="view-title">{title}</h1>
        </div>
        {description ? <p className="page-description">{description}</p> : null}
        {meta ? <div className="page-meta-row">{meta}</div> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}