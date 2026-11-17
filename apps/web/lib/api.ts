"use client";
import { createApi } from "@fitfirst/api";

/** One client per browser tab. Requests go to the same origin (/api/...). */
export const api = createApi({ baseUrl: "", client: "web" });
