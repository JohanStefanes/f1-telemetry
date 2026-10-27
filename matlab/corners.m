function [dist, minKmh] = corners(x, v)
% CORNERS  The main braking zones of one lap: where speed bottoms out at least 15 % below the speed around it.
%   [dist, minKmh] = corners(x, v) takes distance (m) and speed (km/h) of one lap, sorted by distance,
%   and returns each zone's distance from the line and its minimum speed.
%   Same rule as corners() in f1telemetry/pipeline.py, written again from scratch.
WINDOW = 150;  % a corner's slowest point is the slowest within this many metres either side
DROP = 0.85;   % ... and at least 15 % slower than the fastest point 400 m around it

x = x(:);
raw = v(:);
s = movmean(raw, 3);  % smoothed only to find the corners
dist = zeros(0, 1);
minKmh = zeros(0, 1);
if numel(x) < 10
  return
end
for i = 1:numel(x)
  if ~(x(i) > 50 && x(i) < x(end) - 50)
    continue  % the first and last samples sit at the line, where the lap is cut, not in a corner
  end
  near = abs(x - x(i)) <= WINDOW;
  around = abs(x - x(i)) <= 400;
  if s(i) == min(s(near)) && s(i) <= DROP * max(s(around)) && (isempty(dist) || x(i) - dist(end) > 2 * WINDOW)
    dist(end + 1, 1) = x(i);
    minKmh(end + 1, 1) = min(raw(near));
  end
end
end
