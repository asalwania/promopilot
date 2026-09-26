import { proxyToApi } from "@/lib/api/proxy";

function forward(request: Request): Promise<Response> {
  return proxyToApi(request, process.env.API_URL ?? "http://localhost:8000");
}

export {
  forward as DELETE,
  forward as GET,
  forward as PATCH,
  forward as POST,
  forward as PUT,
};
