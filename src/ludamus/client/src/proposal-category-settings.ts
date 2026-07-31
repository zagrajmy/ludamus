const promotionSettings = document.querySelector<HTMLElement>("[data-promotion-settings]");

if (promotionSettings) {
  const claimWindow = promotionSettings.querySelector<HTMLElement>("[data-offer-claim-window]");

  if (claimWindow) {
    const updateClaimWindow = (): void => {
      const selected = promotionSettings.querySelector<HTMLInputElement>(
        'input[name="promotion_mode"]:checked',
      );
      claimWindow.hidden = selected?.value !== "offer_claim";
    };

    promotionSettings.addEventListener("change", updateClaimWindow);
    updateClaimWindow();
  }
}
