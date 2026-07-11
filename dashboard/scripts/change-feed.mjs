export function boundChangeFeed(events, perCategoryLimit = 1000) {
  if (!Number.isInteger(perCategoryLimit) || perCategoryLimit < 1) {
    throw new RangeError('perCategoryLimit must be a positive integer')
  }

  const categoryTotals = {}
  const eventsByCategory = {}
  for (const event of events) {
    const category = event.category
    categoryTotals[category] = (categoryTotals[category] ?? 0) + 1
    const categoryEvents = eventsByCategory[category] ?? (eventsByCategory[category] = [])
    categoryEvents.push(event)
  }

  const retainedEvents = Object.values(eventsByCategory)
    .flatMap((categoryEvents) => categoryEvents
      .sort((a, b) => b.observedAt.localeCompare(a.observedAt) || a.entityId?.localeCompare(b.entityId ?? '') || 0)
      .slice(0, perCategoryLimit))
    .sort((a, b) => b.observedAt.localeCompare(a.observedAt) || a.entityId?.localeCompare(b.entityId ?? '') || 0)

  return {
    events: retainedEvents,
    totalEvents: events.length,
    categoryTotals,
    truncated: retainedEvents.length < events.length,
  }
}
