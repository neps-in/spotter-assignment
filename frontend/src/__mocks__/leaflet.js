// Stub Leaflet so jsdom tests don't need a real DOM with canvas.
const L = {
  divIcon: () => ({}),
  Icon: { Default: { prototype: { _getIconUrl: undefined }, mergeOptions: () => {} } },
}
export default L
