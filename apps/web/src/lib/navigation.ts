import type { ComponentType, SVGProps } from "react";

import { ComposeIcon, FolderIcon, HomeIcon, ImportIcon, LibraryIcon, NeedsYouIcon, SettingsIcon } from "@/components/layout/nav-icons";

export type NavIcon = ComponentType<SVGProps<SVGSVGElement>>;

/** A destination. `planned` items render with a Planned badge and no link. */
export type NavItem = { id: string; href: string; label: string; icon: NavIcon; planned?: boolean };

/** Rail order from Paper · 00 Shell template. */
export const NAV_ITEMS: NavItem[] = [
  { id: "home", href: "/", label: "Home", icon: HomeIcon, planned: true },
  { id: "library", href: "/library", label: "Library", icon: LibraryIcon },
  { id: "compose", href: "/compose", label: "Compose", icon: ComposeIcon },
  { id: "imports", href: "/imports", label: "Imports", icon: ImportIcon, planned: true },
  { id: "projects", href: "/projects", label: "Projects", icon: FolderIcon },
];

/** [Assumption] Paper's Settings row opens System status, the only settings-like page. */
export const SETTINGS_ITEM: NavItem = { id: "settings", href: "/system", label: "Settings", icon: SettingsIcon };

/** Phone tab bar from Paper · 03 Mobile. */
export const TAB_ITEMS: NavItem[] = [
  NAV_ITEMS[0],
  NAV_ITEMS[1],
  { id: "needs-you", href: "/needs-you", label: "Needs you", icon: NeedsYouIcon, planned: true },
];

const ALL = [...NAV_ITEMS, SETTINGS_ITEM];

export function navItemForPath(pathname: string): NavItem | undefined {
  /* The catalog is the detail view for catalog parts in the library. */
  if (pathname === "/catalog" || pathname.startsWith("/catalog/")) return NAV_ITEMS[1];
  return ALL.find((item) => !item.planned && (pathname === item.href || pathname.startsWith(`${item.href}/`)));
}
