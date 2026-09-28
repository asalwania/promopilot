// A scripted stand-in for the browser's EventSource: jsdom has none, and tests need to
// drop, fail and replay a stream on demand.
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private readonly listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  static reset() {
    FakeEventSource.instances = [];
  }

  static latest(): FakeEventSource {
    const latest = FakeEventSource.instances.at(-1);
    if (!latest) throw new Error("no EventSource was opened");
    return latest;
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  get closed() {
    return this.readyState === FakeEventSource.CLOSED;
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }

  send(event: { id: number }) {
    this.sendRaw(JSON.stringify(event), String(event.id));
  }

  sendRaw(data: string, lastEventId = "") {
    this.onmessage?.(new MessageEvent("message", { data, lastEventId }));
  }

  end(payload: { session_id: string; status: string }) {
    this.listeners.get("end")?.(
      new MessageEvent("end", { data: JSON.stringify(payload) }),
    );
  }

  // A network blip: the browser keeps the source and reconnects on its own,
  // sending Last-Event-ID.
  drop() {
    this.readyState = FakeEventSource.CONNECTING;
    this.onerror?.(new Event("error"));
  }

  // An HTTP error (e.g. the proxy's 502): the browser gives up on this source.
  fail() {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.(new Event("error"));
  }
}
