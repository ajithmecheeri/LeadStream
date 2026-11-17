import { redirect } from "next/navigation";

/** LeadStream is an internal application: there is no public home page. Signed-out visitors are sent on to sign-in. */
export default function Home() {
  redirect("/dashboard");
}
