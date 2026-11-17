import type { MetadataRoute } from "next";

/** LeadStream is internal: search engines are asked to stay out. */
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", disallow: "/" } };
}
