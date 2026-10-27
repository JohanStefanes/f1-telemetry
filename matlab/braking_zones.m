function zones = braking_zones(a, b, folder)
% BRAKING_ZONES  Compare two drivers' braking zones on their fastest accurate lap.
%   braking_zones('HUL', 'BOR') reads samples.csv and laps.csv (exported from telemetry.db, see README),
%   prints the minimum speed of each driver in every zone and saves braking_zones.png next to this file.
%   Returns one row per zone: [zone, lap fraction, min km/h a, min km/h b, b - a].
if nargin < 2
  a = 'HUL';
  b = 'BOR';
end
if nargin < 3
  folder = fileparts(mfilename('fullpath'));
end
MATCH = 0.02;  % zones of the two drivers within 2 % of a lap of each other are the same corner

s = read_csv(fullfile(folder, 'samples.csv'), '%q%f%f%f');  % Driver, LapNumber, Distance, Speed
l = read_csv(fullfile(folder, 'laps.csv'), '%q%f%f%f');     % Driver, LapNumber, LapTimeS, IsAccurate

drivers = {a, b};
for k = 1:2
  ok = strcmp(l{1}, drivers{k}) & l{4} == 1 & ~isnan(l{3});
  if ~any(ok)
    error('No accurate lap for %s in laps.csv.', drivers{k});
  end
  numbers = l{2}(ok);
  [t(k), j] = min(l{3}(ok));
  lap(k) = numbers(j);
  in = strcmp(s{1}, drivers{k}) & s{2} == lap(k) & ~isnan(s{3}) & ~isnan(s{4});
  [x{k}, order] = sort(s{3}(in));
  speed = s{4}(in);
  v{k} = speed(order);
  [d, m{k}] = corners(x{k}, v{k});
  frac{k} = d / x{k}(end);  % as a fraction of the lap, so both laps line up although distance is estimated
end

zones = zeros(0, 5);
for i = 1:numel(frac{1})
  [gap, j] = min(abs(frac{2} - frac{1}(i)));
  if ~isempty(gap) && gap <= MATCH
    zones(end + 1, :) = [i, frac{1}(i), m{1}(i), m{2}(j), m{2}(j) - m{1}(i)];
  end
end

fprintf('Fastest laps: %s %s (lap %d), %s %s (lap %d)\n', a, laptime(t(1)), lap(1), b, laptime(t(2)), lap(2));
fprintf('%4s %7s %9s %9s %7s\n', 'Zone', 'Lap %', [a ' km/h'], [b ' km/h'], 'Delta');
fprintf('%4d %7.1f %9.0f %9.0f %+7.0f\n', [zones(:, 1), 100 * zones(:, 2), zones(:, 3:5)]');

colors = [0.15 0.15 0.15; 0.85 0.1 0.2];
fig = figure('Visible', 'off', 'Position', [0 0 1200 500]);
hold on
for k = 1:2
  plot(100 * x{k} / x{k}(end), v{k}, 'Color', colors(k, :), 'LineWidth', 1.2);
end
for k = 1:2
  plot(100 * frac{k}, m{k}, 'o', 'Color', colors(k, :), 'MarkerFaceColor', colors(k, :), 'HandleVisibility', 'off');
end
for i = 1:size(zones, 1)
  text(100 * zones(i, 2), min(zones(i, 3:4)) - 18, sprintf('%d: %+.0f', zones(i, 1), zones(i, 5)), ...
       'HorizontalAlignment', 'center');
end
hold off
grid on
ylim([0 360]);
xlabel('Lap distance (%)');
ylabel('Speed (km/h)');
title(sprintf('Braking zones, fastest laps: minimum speed, %s minus %s', b, a));
legend({sprintf('%s %s', a, laptime(t(1))), sprintf('%s %s', b, laptime(t(2)))}, 'Location', 'northoutside', 'Orientation', 'horizontal');
print(fig, fullfile(folder, 'braking_zones.png'), '-dpng', '-r120');
close(fig);
end

function c = read_csv(path, fmt)
f = fopen(path);
if f < 0
  error('Cannot open %s: export it from telemetry.db first (see README).', path);
end
c = textscan(f, fmt, 'Delimiter', ',', 'HeaderLines', 1, 'EmptyValue', NaN);
fclose(f);
end

function s = laptime(t)
s = sprintf('%d:%06.3f', floor(t / 60), mod(t, 60));
end
