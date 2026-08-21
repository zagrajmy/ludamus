import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";

const bootstrap = {
  agentHost: "localhost:8787",
  capabilityToken: "mock-token",
  copy: {
    backLabel: "Back to conversations",
    closeLabel: "Close Parley",
    connectionError: "Could not connect to Parley.",
    copyLink: "Copy message link",
    deletedMessage: "Message deleted",
    deleteLabel: "Delete message",
    emptySession: "You found the table first. Leave a note for the others.",
    emptySphere: "Quiet in here. Say hello before someone starts a rules debate.",
    errorArchived: "This conversation is archived.",
    errorExpired: "Your Parley access expired. Reopen Parley to continue.",
    errorForbidden: "You do not have permission to do that.",
    errorInvalid: "That message could not be sent.",
    errorMuted: "Your writing access is currently muted.",
    errorRateLimited: "Too many messages. Wait a moment and try again.",
    errorUnknown: "Something went wrong. Try again.",
    loadEarlier: "Load earlier messages",
    loading: "Gathering conversations…",
    messageLabel: "Message",
    messageTooLong: "Messages can be up to 1,000 characters.",
    moderatorDelete: "Delete as moderator",
    muteIndefinitely: "Mute indefinitely",
    muteLabel: "Change writing access",
    muteOneDay: "Mute for 24 hours",
    muteOneHour: "Mute for 1 hour",
    muteSevenDays: "Mute for 7 days",
    offline: "Parley lost the thread. Reconnecting…",
    online: "online",
    presence: "people around",
    readOnly: "This parley has ended, but you can still read what was said.",
    reported: "Message reported.",
    reportMessage: "Report message",
    retry: "Try again",
    restoreWriting: "Restore writing access",
    roomsLabel: "Conversations",
    sending: "Sending…",
    sendLabel: "Send message",
    sessionRoom: "Programme point",
    sphereRoom: "Common room",
    title: "Parley",
    unread: "Unread",
    writePlaceholder: "Write a message…",
  },
  csrfToken: "mock-csrf",
  rooms: [
    { canModerate: true, canWrite: true, id: "sphere:1", kind: "sphere", title: "Zagrajmy" },
    { canModerate: true, canWrite: false, id: "session:42", kind: "session", title: "Mothership" },
  ],
  sphere: { id: "1", name: "Zagrajmy" },
  user: { avatarUrl: "", id: "1", name: "E2E Manager" },
};

test.describe.configure({ mode: "serial" });

test("Parley launcher opens an accessible responsive conversation panel", async ({ page }) => {
  await page.route("**/parley/bootstrap/", (route) =>
    route.fulfill({ contentType: "application/json", json: bootstrap }),
  );
  await page.route("http://localhost:8787/auth/exchange", (route) =>
    route.fulfill({
      headers: {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Origin": "http://localhost:8000",
      },
      status: 204,
    }),
  );

  try {
    await page.goto("/multiverse/panel/");
    await page.getByLabel("Enable Parley conversations").check();
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();

    await page.goto("/");
    const launcher = page.getByRole("button", { name: "Open Parley" });
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await launcher.click();

    const panel = page.getByRole("dialog", { name: "Parley" });
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("navigation", { name: "Conversations" })).toBeVisible();
    await expect(panel.getByLabel("Message")).toBeVisible();
    await analyzePageAccessibility(page);
    await page.screenshot({ path: "screenshots/parley-desktop.png" });

    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(launcher).toBeFocused();

    await page.setViewportSize({ height: 844, width: 390 });
    await launcher.click();
    await expect(page.getByRole("dialog", { name: "Parley" })).toBeVisible();
    await expect(page.getByPlaceholder("Write a message…")).toBeVisible();
    await page.screenshot({ path: "screenshots/parley-mobile.png" });
  } finally {
    await page.goto("/multiverse/panel/");
    await page.getByLabel("Enable Parley conversations").uncheck();
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();
  }
});
