import {
  Activity,
  GitBranch,
  GitCommitHorizontal,
  LayoutDashboard,
  Search,
  Zap,
} from "lucide-react";

export type NavItem =
  | "overview"
  | "architecture"
  | "api-explorer"
  | "sequence-diagrams"
  | "deep-dive"
  | "simulation";

export const NAV_ITEMS: {
  key: NavItem;
  label: string;
  icon: typeof LayoutDashboard;
}[] = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "architecture", label: "Architecture", icon: GitBranch },
  { key: "api-explorer", label: "API Explorer", icon: Zap },
  { key: "sequence-diagrams", label: "Sequence Diagrams", icon: GitCommitHorizontal },
  { key: "deep-dive", label: "Deep Dive", icon: Search },
  { key: "simulation", label: "Simulation", icon: Activity },
];