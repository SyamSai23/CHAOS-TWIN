import {
  Activity,
  GitBranch,
  GitCommitHorizontal,
  LayoutDashboard,
  Search,
  Zap,
  BookOpen,
} from "lucide-react";

export type NavItem =
  | "landing"
  | "dashboard"
  | "understanding"
  | "architecture"
  | "api-explorer"
  | "sequence-diagrams"
  | "deep-dive"
  | "simulation"
  | "workspace";  // kept for any legacy internal references

export const NAV_GROUPS: {
  label: string;
  items: {
    key: NavItem;
    label: string;
    icon: typeof LayoutDashboard;
    requiresScan?: boolean;
    comingSoon?: boolean;
  }[];
}[] = [
  {
    label: "Explore",
    items: [
      { key: "dashboard",        label: "Dashboard",        icon: LayoutDashboard },
      { key: "understanding",    label: "Understanding",    icon: BookOpen },
      { key: "architecture",     label: "Architecture",     icon: GitBranch,            requiresScan: true, comingSoon: true },
      { key: "api-explorer",     label: "API Explorer",     icon: Zap,                  requiresScan: true, comingSoon: true },
      { key: "sequence-diagrams",label: "Sequence Diagrams",icon: GitCommitHorizontal,  requiresScan: true, comingSoon: true },
      { key: "deep-dive",        label: "Deep Dive",        icon: Search,               requiresScan: true, comingSoon: true },
      { key: "simulation",       label: "Simulation",       icon: Activity,             requiresScan: true, comingSoon: true },
    ],
  },
];

export const NAV_ITEMS: {
  key: NavItem;
  label: string;
  icon: typeof LayoutDashboard;
  requiresScan?: boolean;
}[] = NAV_GROUPS.flatMap((group) => group.items);
