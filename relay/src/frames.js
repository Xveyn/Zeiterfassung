// relay/src/frames.js
// Nachrichtenrahmen der Box: 1 Byte Typ, danach Nutzbytes. Die Nutzbytes sind opak (kein JSON,
// kein Logging). Nur Uint8Array/DataView, kein Buffer.
export const FRAME = { put: 0x01, slot: 0x02, ok: 0x03 };

// Nutzbytes eines `put`; null bei Text, falschem Typ-Byte oder leerer Nachricht.
export function decodePut(message) {
  let view;
  if (message instanceof ArrayBuffer) view = new Uint8Array(message);
  else if (message instanceof Uint8Array) view = message;
  else return null;
  if (view.length === 0 || view[0] !== FRAME.put) return null;
  return view.slice(1);
}

function withVersion(type, ver, extra) {
  const out = new Uint8Array(5 + extra);
  out[0] = type;
  new DataView(out.buffer).setUint32(1, ver, false);
  return out;
}

export function encodeSlot(ver, data) {
  const out = withVersion(FRAME.slot, ver, data.length);
  out.set(data, 5);
  return out;
}

export function encodeOk(ver) {
  return withVersion(FRAME.ok, ver, 0);
}
