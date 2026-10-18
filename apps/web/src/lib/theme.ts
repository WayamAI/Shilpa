/**
 * Theme constants shared by the server layout and the client provider.
 *
 * This must not live in the "use client" context module: a server component
 * importing a value from a client module gets a client reference, not the
 * string, so the layout's cookie lookup always missed and every first paint
 * was light.
 */
export type ThemeMode = "light" | "dark";

export const THEME_STORAGE_KEY = "shilpa-theme";
