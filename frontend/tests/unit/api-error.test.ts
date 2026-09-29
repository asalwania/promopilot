import { describe, expect, it } from "vitest";

import { apiError, ApiRequestError, referenceIdOf } from "@/lib/api/reason";

const REFERENCE = "6f1c2a7e-0b1d-4c55-9a0e-3d2b1f0c9e11";

describe("apiError", () => {
  it("reads the API's error schema (ADR 0071)", async () => {
    const response = Response.json(
      {
        detail: "plan revision 1 is approved and final",
        code: "conflict",
        reference_id: REFERENCE,
        errors: null,
      },
      { status: 409, headers: { "x-request-id": REFERENCE } },
    );

    expect(await apiError(response)).toEqual({
      message: "plan revision 1 is approved and final",
      code: "conflict",
      referenceId: REFERENCE,
      status: 409,
    });
  });

  it("shows a 422's readable detail, not its field list", async () => {
    const response = Response.json(
      {
        detail: "brief: String should have at most 2000 characters",
        code: "validation_failed",
        reference_id: REFERENCE,
        errors: [
          {
            loc: "body.brief",
            message: "String should have at most 2000 characters",
          },
        ],
      },
      { status: 422 },
    );

    expect(await apiError(response)).toMatchObject({
      message: "brief: String should have at most 2000 characters",
      code: "validation_failed",
      referenceId: REFERENCE,
    });
  });

  it("takes the reference id from X-Request-ID when the body has none", async () => {
    const response = new Response("Internal Server Error", {
      status: 500,
      headers: { "x-request-id": REFERENCE },
    });

    expect(await apiError(response)).toEqual({
      message: "HTTP 500",
      code: null,
      referenceId: REFERENCE,
      status: 500,
    });
  });

  it("still reads FastAPI's older validation list", async () => {
    const response = Response.json(
      { detail: [{ loc: ["body", "brief"], msg: "the brief is empty" }] },
      { status: 422 },
    );

    expect(await apiError(response)).toEqual({
      message: "the brief is empty",
      code: null,
      status: 422,
    });
  });

  it("falls back to the status when the body is not JSON", async () => {
    const response = new Response("<html>bad gateway</html>", { status: 502 });

    expect(await apiError(response)).toEqual({
      message: "HTTP 502",
      code: null,
      status: 502,
    });
  });
});

describe("ApiRequestError", () => {
  it("carries the reference id for the page to show", () => {
    const error = new ApiRequestError("Couldn't load", REFERENCE);

    expect(error.message).toBe("Couldn't load");
    expect(referenceIdOf(error)).toBe(REFERENCE);
    expect(referenceIdOf(new Error("plain"))).toBeUndefined();
    expect(referenceIdOf(null)).toBeUndefined();
  });
});
