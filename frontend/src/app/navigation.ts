import {
  Activity,
  GitBranch,
  GitCommitHorizontal,
  LayoutDashboard,
  Sparkles,
  Search,
  Zap,
} from "lucide-react";

export type NavItem =
  | "workspace"
  | "overview"
  | "architecture"
  | "api-explorer"
  | "sequence-diagrams"
  | "deep-dive"
  | "simulation";

export const NAV_GROUPS: {
  label: string;
  items: {
    key: NavItem;
    label: string;
    icon: typeof LayoutDashboard;
    requiresScan?: boolean;
  }[];
}[] = [
  {
    label: "Start Here",
    items: [
      { key: "workspace", label: "Summary", icon: LayoutDashboard },
      { key: "overview", label: "Evidence", icon: Sparkles, requiresScan: true },
    ],
  },
  {
    label: "Understand",
    items: [
      { key: "architecture", label: "Architecture", icon: GitBranch, requiresScan: true },
      { key: "deep-dive", label: "Components", icon: Search, requiresScan: true },
      { key: "api-explorer", label: "Routes", icon: Zap, requiresScan: true },
      { key: "sequence-diagrams", label: "Sequences", icon: GitCommitHorizontal, requiresScan: true },
    ],
  },
  {
    label: "Go Deeper",
    items: [
      { key: "simulation", label: "Simulation", icon: Activity, requiresScan: true },
    ],
  },
];

export const NAV_ITEMS: {
  key: NavItem;
  label: string;
  icon: typeof LayoutDashboard;
  requiresScan?: boolean;
}[] = NAV_GROUPS.flatMap((group) => group.items);