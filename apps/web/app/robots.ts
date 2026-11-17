import type { MetadataRoute } from "next";
import { SITE_URL } from "./_home/site";

/** Search engines may index the home page and the privacy, terms and contact pages; the app behind sign-in is of no
 * use to them. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: ["/$", "/privacy", "/terms", "/contact"], disallow: "/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
