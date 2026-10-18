import { redirect } from "next/navigation";

/** proxy.ts normally redirects first; this covers direct server renders. */
export default function Home() {
  redirect("/projects");
}
