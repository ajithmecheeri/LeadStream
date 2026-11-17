import type { Metadata } from "next";
import { LegalPage } from "../_legal/LegalPage";
import { ContactForm } from "./ContactForm";

export const metadata: Metadata = {
  title: "Contact",
  description: "Write to the BrewMyJob team: questions, help, feedback or a privacy request.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  return (
    <LegalPage title="Contact us" path="/contact">
      <p>
        Questions, help with your account, feedback, or a privacy request (to see, correct or delete your data): write to us here. We
        read every message. For a privacy request, use the email address on your BrewMyJob account so we can find it.
      </p>
      <ContactForm />
    </LegalPage>
  );
}
