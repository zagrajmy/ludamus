import { Context } from "effect";

import type { Sphere } from "../sphere.js";

export class CurrentSphere extends Context.Service<CurrentSphere, Sphere>()(
  "@zagrajmy/core/CurrentSphere"
) {}
