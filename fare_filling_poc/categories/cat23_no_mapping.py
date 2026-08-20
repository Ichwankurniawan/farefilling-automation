from categories.base import CategoryResolver


class Cat23Resolver(CategoryResolver):
    category = "CAT23"
    # DataMapping: "-- no category-specific mapping defined --" for the
    # main entry, plus a separate note that "Override Dates" is CONSTANT
    # "Not needed -- the format uses calendar dates" (i.e. explicitly
    # never populated, not just unmapped). has_mapping=False, same as
    # CAT09/13/18/20/21/22/26/27/28/29/33.
    #
    # NOTE: this category's template columns are shifted one position
    # left compared to every other category (LOC1 is missing entirely --
    # Zone1 sits where LOC1 normally would) -- see CAT23_COLS in
    # template_writer.py (AltGenTariff=O, AltGenRule=P, OW/RT=M instead
    # of the usual P/Q/N).
    has_mapping = False
    output_fields = []
