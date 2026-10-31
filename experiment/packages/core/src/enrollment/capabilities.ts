import { claimOffer } from "./claim-offer-capability.js";
import { declineOffer } from "./decline-offer-capability.js";
import { expireOffers } from "./expire-offers-capability.js";
import { readEnrollFooter } from "./read-enroll-footer-capability.js";
import { readEnrollmentForm } from "./read-enrollment-form-capability.js";
import { readOffer } from "./read-offer-capability.js";
import { submitEnrollments } from "./submit-enrollments-capability.js";
import { toggleBookmark } from "./toggle-bookmark-capability.js";

export const enrollmentCapabilities = [
  readEnrollmentForm,
  readEnrollFooter,
  submitEnrollments,
  readOffer,
  claimOffer,
  declineOffer,
  expireOffers,
  toggleBookmark,
] as const;
