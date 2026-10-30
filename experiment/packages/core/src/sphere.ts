import { Schema } from "effect";

export const SphereId = Schema.Int.pipe(Schema.brand("SphereId"));
export type SphereId = typeof SphereId.Type;

export const Sphere = Schema.Struct({
  domain: Schema.String,
  id: SphereId,
  name: Schema.String,
});
export type Sphere = typeof Sphere.Type;
