// VISION · Traffic map (browser module for the local dashboard)
// Load Google Maps with the geometry library:
//   <script src="https://maps.googleapis.com/maps/api/js?key=YOUR_KEY&libraries=geometry"></script>
// Note: the `styles` array below only applies to maps created WITHOUT a mapId (cloud styling overrides it).

export const VISION_MAP_STYLE = [
  // Base geometry + landscape
  { elementType: 'geometry', stylers: [{ color: '#07080A' }] },
  { featureType: 'landscape', elementType: 'geometry', stylers: [{ color: '#07080A' }] },
  // Water
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#101217' }] },
  // Roads: standard + highways
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#1C1F26' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#3A3222' }] },
  // Quiet HUD labels
  { elementType: 'labels.text.fill', stylers: [{ color: '#9A8F76' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#07080A' }] },
  // POI + transit labels off (minimal HUD); POI geometry blends into the base
  { featureType: 'poi', elementType: 'geometry', stylers: [{ color: '#07080A' }] },
  { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
  { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] },
];

export const TRAFFIC_COLORS = {
  NORMAL: '#67C7EB',
  SLOW: '#FBCA03',
  TRAFFIC_JAM: '#AA0505',
};

export function createVisionMap(el, center, zoom = 12) {
  return new google.maps.Map(el, {
    center,
    zoom,
    styles: VISION_MAP_STYLE,
    backgroundColor: '#07080A',
    disableDefaultUI: true,
    zoomControl: true,
    clickableIcons: false,
  });
}

// Draw one route coloured by live traffic.
// `route` is a Routes API computeRoutes result, requested with:
//   routingPreference: 'TRAFFIC_AWARE_OPTIMAL', extraComputations: ['TRAFFIC_ON_POLYLINE'],
//   X-Goog-FieldMask: routes.polyline.encodedPolyline,routes.travelAdvisory.speedReadingIntervals
// Returns the polylines so the caller can clear them on the next poll.
export function drawTrafficRoute(map, route) {
  const path = google.maps.geometry.encoding.decodePath(route.polyline.encodedPolyline);
  const intervals = route.travelAdvisory?.speedReadingIntervals?.length
    ? route.travelAdvisory.speedReadingIntervals
    : [{ startPolylinePointIndex: 0, endPolylinePointIndex: path.length - 1, speed: 'NORMAL' }];

  return intervals.map((iv) => {
    const start = iv.startPolylinePointIndex ?? 0; // index 0 is omitted in the JSON response
    const end = iv.endPolylinePointIndex ?? path.length - 1;
    return new google.maps.Polyline({
      map,
      path: path.slice(start, end + 1),
      strokeColor: TRAFFIC_COLORS[iv.speed] || TRAFFIC_COLORS.NORMAL,
      strokeOpacity: 0.95,
      strokeWeight: iv.speed === 'TRAFFIC_JAM' ? 6 : 4,
      zIndex: iv.speed === 'TRAFFIC_JAM' ? 3 : iv.speed === 'SLOW' ? 2 : 1,
    });
  });
}

export function clearPolylines(lines) {
  (lines || []).forEach((l) => l.setMap(null));
}
