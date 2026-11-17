import { describe, expect, it } from "vitest";
import { fileName, sizeLabel, uploadProblem } from "./documents";

describe("download names", () => {
  it("adds the extension for the file's type", () => {
    expect(fileName("Cloud and AI", "application/pdf")).toBe("Cloud and AI.pdf");
    expect(fileName("CV.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")).toBe("CV.docx");
    expect(fileName("Notes", "text/plain; charset=utf-8")).toBe("Notes.txt");
    expect(fileName("a/b: c", "application/octet-stream")).toBe("a b  c");
  });
});

describe("sizes and upload checks", () => {
  it("shows sizes in KB and MB", () => {
    expect(sizeLabel(312_400)).toBe("312 KB");
    expect(sizeLabel(1_420_000)).toBe("1.4 MB");
    expect(sizeLabel(null)).toBe("");
  });

  it("explains files that won't be accepted", () => {
    expect(uploadProblem({ name: "cv.pdf", size: 100_000 })).toBeNull();
    expect(uploadProblem({ name: "cv.DOCX", size: 100_000 })).toBeNull();
    expect(uploadProblem({ name: "cv.doc", size: 100_000 })).toMatch(/old Word file/);
    expect(uploadProblem({ name: "cv.png", size: 100_000 })).toMatch(/only PDF/);
    expect(uploadProblem({ name: "cv.pdf", size: 6_000_000 })).toMatch(/larger than 5 MB/);
  });
});
