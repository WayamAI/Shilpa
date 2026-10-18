import { Activity, FolderKanban, type LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; group: string; icon: LucideIcon };

export const NAV_ITEMS: NavItem[] = [
  { href: "/projects", label: "Projects", group: "Studio", icon: FolderKanban },
  { href: "/system", label: "System", group: "Operations", icon: Activity },
];

export function navItemForPath(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
}
