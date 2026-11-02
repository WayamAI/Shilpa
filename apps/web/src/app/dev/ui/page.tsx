import { notFound } from "next/navigation";

import { Gallery } from "./gallery";

/** Development-only primitive gallery, for checking states against Paper · Foundations. */
export default function DevUiPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Gallery />;
}
