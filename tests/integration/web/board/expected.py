from ludamus.pacts.listing import (
    ListingContact,
    ListingDTO,
    ListingRole,
    ListingSeeking,
    ListingStatus,
    ListingTagDTO,
)


def listing_dto(listing):
    listing.refresh_from_db()
    return ListingDTO(
        pk=listing.pk,
        sphere_id=listing.sphere_id,
        author_id=listing.author_id,
        author_name=listing.author.full_name,
        role=ListingRole(listing.role),
        seeking=ListingSeeking(listing.seeking),
        title=listing.title,
        what=listing.what,
        description=listing.description,
        tags=[
            ListingTagDTO(pk=tag.pk, name=tag.name)
            for tag in listing.picked_tags.order_by("name")
        ],
        seats=listing.seats,
        medium=listing.medium,
        place=listing.place,
        starts_at=listing.starts_at,
        when_text=listing.when_text,
        contact=ListingContact(listing.contact),
        status=ListingStatus(listing.status),
        opened_at=listing.opened_at,
        header_image_url=listing.header_image_url,
        header_image_original_name=listing.header_image_original_name,
    )
