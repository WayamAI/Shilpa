import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/** Route gate: signed-out visitors go to sign-in; signed-in visitors skip it. */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  const isLogin = pathname === "/login";

  if (!session && !isLogin) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  if (session && (isLogin || pathname === "/")) {
    const url = request.nextUrl.clone();
    url.pathname = "/home";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // /v1 is the API rewrite: excluded so uploads are streamed, not buffered, and SSE is untouched.
  matcher: ["/((?!v1/|_next/static|_next/image|brand|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
