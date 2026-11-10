import process from 'node:process';
import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import yaml from '@modyfi/vite-plugin-yaml';
import svgr from 'vite-plugin-svgr';
import JSZip from 'jszip';
import polyline from '@mapbox/polyline';

// 统一数据接口基址 /data/：
//   activities.json          全部活动（原始 JSON）
//   activities.csv           全部活动（表格）
//   gpx/all.zip              全部 GPS 轨迹 GPX 打包（由轨迹线生成，含插值时间戳）
//   types/{slug}.json        按运动类型拆分的活动 JSON
//   gpx/{slug}.zip           按运动类型拆分的 GPX 打包
//   index.json               接口自描述清单（类型/数量/可用资源）
function activitiesDataPlugin() {
  const slugify = (t: string) => t.toLowerCase().replace(/\s+/g, '-');
  const esc = (value: unknown) => {
    const s = String(value ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const xmlEsc = (s: string) =>
    s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

  // 由轨迹线生成 GPX：时间为起点+匀速插值（轨迹线本身不含逐点时间）
  function buildGpx(
    name: string,
    coords: [number, number][],
    startDateLocal: string,
    movingSeconds: number,
    elevations?: number[],
  ): string {
    // start_date_local 有两种格式：'2026-11-06 08:28'（无时区）与
    // '2024-07-12 07:11:55+00:00'（带时区）——统一成合法 ISO 再解析
    const iso = startDateLocal.includes('T')
      ? startDateLocal
      : startDateLocal.replace(' ', 'T');
    const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
    const start = new Date(hasTz ? iso : `${iso}Z`);
    if (Number.isNaN(start.getTime())) {
      throw new Error(`Invalid start_date_local: ${startDateLocal}`);
    }
    const step = coords.length > 1 ? movingSeconds / (coords.length - 1) : 0;
    const pts = coords
      .map(([lat, lon], i) => {
        const t = new Date(start.getTime() + step * 1000 * i)
          .toISOString()
          .replace(/\.\d{3}Z$/, 'Z');
        // 海拔：把 Strava streams 的采样按位置比例映射到轨迹点上
        const ele =
          elevations && elevations.length > 0
            ? elevations[
                Math.min(
                  elevations.length - 1,
                  Math.round(
                    (i * (elevations.length - 1)) /
                      Math.max(coords.length - 1, 1),
                  ),
                )
              ]
            : null;
        const eleXml =
          ele !== null && Number.isFinite(ele)
            ? `<ele>${ele.toFixed(1)}</ele>`
            : '';
        return `      <trkpt lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}">${eleXml}<time>${t}</time></trkpt>`;
      })
      .join('\n');
    return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="FIT.PAGE" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>${xmlEsc(name)}</name></metadata>
  <trk><name>${xmlEsc(name)}</name><trkseg>
${pts}
  </trkseg></trk>
</gpx>`;
  }

  const debug = { made: 0, errors: [] as string[] };

  return {
    name: 'emit-activities-data',
    apply: 'build' as const,
    async generateBundle() {
      const source = fs.readFileSync(
        path.resolve(__dirname, 'src/static/activities.json'),
        'utf-8',
      );
      this.emitFile({
        type: 'asset',
        fileName: 'data/activities.json',
        source,
      });

      // 海拔缓存（由 fetch_elevations.py 在同步工作流中抓取并提交）
      let elevationCache: Record<string, number[]> = {};
      try {
        elevationCache = JSON.parse(
          fs.readFileSync(
            path.resolve(__dirname, 'run_page/elevation_cache.json'),
            'utf-8',
          ),
        ) as Record<string, number[]>;
      } catch {
        elevationCache = {};
      }

      // CSV 版本：字段与页面「下载数据」按钮一致
      const header = [
        '日期',
        '类型',
        '名称',
        '距离(km)',
        '时长',
        '平均心率',
        '平均速度(m/s)',
        '累计爬升(m)',
        '地点',
        '来源',
        '活动ID',
      ];
      const activities = JSON.parse(source) as {
        run_id: number;
        start_date_local: string;
        type: string;
        name: string;
        distance: number;
        moving_time: string;
        average_heartrate: number | null;
        average_speed: number | null;
        elevation_gain: number | null;
        location_country: string | null;
        source: string;
        summary_polyline: string | null;
      }[];
      const lines = activities
        .slice()
        .sort((x, y) => y.start_date_local.localeCompare(x.start_date_local))
        .map((a) =>
          [
            esc(a.start_date_local.slice(0, 16).replace('T', ' ')),
            esc(a.type),
            esc(a.name || ''),
            esc((a.distance / 1000).toFixed(2)),
            esc(a.moving_time),
            esc(a.average_heartrate ?? ''),
            esc(a.average_speed ?? ''),
            esc(a.elevation_gain ?? ''),
            esc(a.location_country ?? ''),
            esc(a.source ?? ''),
            esc(String(a.run_id)),
          ].join(',')
        );
      // BOM 保证 Excel 打开中文不乱码
      const csv = `\uFEFF${[header.map(esc).join(','), ...lines].join('\r\n')}`;
      this.emitFile({
        type: 'asset',
        fileName: 'data/activities.csv',
        source: csv,
      });

      // 按运动类型分组
      const parseMovingSeconds = (t: string): number => {
        const parts = t.split(':').map((n) => parseInt(n, 10) || 0);
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        if (parts.length === 2) return parts[0] * 60 + parts[1];
        return 0;
      };
      const byType = new Map<
        string,
        {
          run_id: number;
          name: string;
          type: string;
          start_date_local: string;
          moving_time: string;
          distance: number;
          summary_polyline: string | null;
        }[]
      >();
      for (const a of activities) {
        const arr = byType.get(a.type) ?? [];
        arr.push(a);
        byType.set(a.type, arr);
      }

      // GPX 生成 + 按类型打包
      const typeIndex: {
        type: string;
        slug: string;
        count: number;
        gpxCount: number;
        json: string;
        gpx: string;
      }[] = [];
      for (const [type, arr] of [...byType.entries()].sort((x, y) => y[1].length - x[1].length)) {
        const slug = slugify(type);
        this.emitFile({
          type: 'asset',
          fileName: `data/types/${slug}.json`,
          source: JSON.stringify(
            arr.sort((x, y) => y.start_date_local.localeCompare(x.start_date_local)),
            null,
            0,
          ),
        });

        const gpxActivities = arr.filter(
          (a) => a.summary_polyline && a.summary_polyline.length > 20,
        );
        if (gpxActivities.length > 0) {
          const zip = new JSZip();
          const usedNames = new Set<string>();
          for (const a of gpxActivities) {
            try {
              const coords = polyline.decode(
                a.summary_polyline as string,
              ) as [number, number][];
              const movingSeconds = parseMovingSeconds(a.moving_time);
              const fileNameBase = `${a.start_date_local.slice(0, 10)} ${a.name || `${a.type} ${a.run_id}`}`
                .replace(/[\\/:*?"<>|]/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
              let fileName = `${fileNameBase}.gpx`;
              let n = 2;
              while (usedNames.has(fileName)) {
                fileName = `${fileNameBase} (${n++}).gpx`;
              }
              usedNames.add(fileName);
              zip.file(
                fileName,
                buildGpx(
                  a.name || `${type} ${a.run_id}`,
                  coords,
                  a.start_date_local,
                  movingSeconds,
                  elevationCache[String(a.run_id)],
                ),
              );
              debug.made += 1;
            } catch (err) {
              debug.errors.push(`${a.run_id}: ${(err as Error).message}`);
            }
          }
          const gpxZip = await zip.generateAsync({ type: 'nodebuffer' });
          console.log(
            `[data-debug] ${type}: zip ${(gpxZip as Buffer).length}B, made=${debug.made}, misses=${debug.errors.length}`,
            debug.errors.slice(0, 3),
          );
          this.emitFile({
            type: 'asset',
            fileName: `data/gpx/${slug}.zip`,
            source: gpxZip,
          });
          typeIndex.push({
            type,
            slug,
            count: arr.length,
            gpxCount: debug.made,
            json: `data/types/${slug}.json`,
            gpx: `data/gpx/${slug}.zip`,
          });
        } else {
          typeIndex.push({
            type,
            slug,
            count: arr.length,
            gpxCount: 0,
            json: `data/types/${slug}.json`,
            gpx: '',
          });
        }
      }

      // 全部 GPX 打包
      const allGpxActivities = activities.filter(
        (a) => a.summary_polyline && a.summary_polyline.length > 20,
      );
      if (allGpxActivities.length > 0) {
        const zip = new JSZip();
        const usedNames = new Set<string>();
        for (const a of allGpxActivities) {
          try {
            const coords = polyline.decode(
              a.summary_polyline as string,
            ) as [number, number][];
            const movingSeconds = parseMovingSeconds(a.moving_time);
            const fileNameBase = `${a.start_date_local.slice(0, 10)} ${a.name || `${a.type} ${a.run_id}`}`
              .replace(/[\\/:*?"<>|]/g, ' ')
              .replace(/\s+/g, ' ')
              .trim();
            let fileName = `${fileNameBase}.gpx`;
            let n = 2;
            while (usedNames.has(fileName)) {
              fileName = `${fileNameBase} (${n++}).gpx`;
            }
            usedNames.add(fileName);
            zip.file(
              fileName,
              buildGpx(
                a.name || `${a.type} ${a.run_id}`,
                coords,
                a.start_date_local,
                movingSeconds,
                elevationCache[String(a.run_id)],
              ),
            );
          } catch {
            // 轨迹线解码失败的条目跳过
          }
        }
        const gpxZip = await zip.generateAsync({ type: 'nodebuffer' });
        this.emitFile({
          type: 'asset',
          fileName: 'data/gpx/all.zip',
          source: gpxZip,
        });
      }

      // 按月份拆分（YYYY-MM 一组，date_local 的本地月份口径）
      const byMonth = new Map<
        string,
        { start_date_local: string }[]
      >();
      for (const a of activities) {
        const month = a.start_date_local.slice(0, 7);
        const arr = byMonth.get(month) ?? [];
        arr.push(a);
        byMonth.set(month, arr);
      }
      for (const [month, arr] of [...byMonth.entries()].sort((x, y) =>
        x[0].localeCompare(y[0]),
      )) {
        this.emitFile({
          type: 'asset',
          fileName: `data/months/${month}.json`,
          source: JSON.stringify(arr, null, 0),
        });
      }
      const monthsIndex = [...byMonth.entries()]
        .sort((x, y) => x[0].localeCompare(y[0]))
        .map(([month, arr]) => ({
          month,
          count: arr.length,
          json: `data/months/${month}.json`,
        }));

      // 接口自描述清单
      this.emitFile({
        type: 'asset',
        fileName: 'data/index.json',
        source: JSON.stringify(
          {
            generated_at: new Date().toISOString(),
            total: activities.length,
            base: '',
            endpoints: {
              activities_all: 'data/activities.json',
              activities_csv: 'data/activities.csv',
              gpx_all: 'data/gpx/all.zip',
            },
            months: monthsIndex,
            types: typeIndex,
          },
          null,
          2,
        ),
      });
    },
  };
}

const colorClassMapping: { [key: string]: string } = {
  '#1a1a1a': 'svg-color-bg',
  '#222': 'svg-color-bg',
  '#444': 'svg-color-inactive-cell',
  '#4dd2ff': 'svg-color-active-cell',
  '#fff': 'svg-color-text',
  '#e1ed5e': 'svg-color-text',
};

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    activitiesDataPlugin(),
    react(),
    tailwindcss(),
    yaml(),
    svgr({
      include: ['**/*.svg'],
      svgrOptions: {
        exportType: 'named',
        namedExport: 'ReactComponent',
        plugins: ['@svgr/plugin-svgo', '@svgr/plugin-jsx'],
        svgoConfig: {
          floatPrecision: 2,
          plugins: [
            {
              name: 'preset-default',
              params: {
                overrides: {
                  removeTitle: false,
                  removeViewBox: false,
                },
              },
            },
            {
              name: 'addClassesByFillColor',
              fn: () => {
                return {
                  element: {
                    enter: (node: {
                      attributes: {
                        fill?: string;
                        stroke?: string;
                        class?: string;
                      };
                    }) => {
                      const fillColor = node.attributes.fill;
                      if (fillColor) {
                        const lowerCaseFill = fillColor.toLowerCase();
                        if (colorClassMapping[lowerCaseFill]) {
                          node.attributes.class =
                            colorClassMapping[lowerCaseFill];
                        }
                      }
                      const strokeColor = node.attributes.stroke;
                      if (strokeColor) {
                        const lowerCaseStroke = strokeColor.toLowerCase();
                        if (colorClassMapping[lowerCaseStroke]) {
                          const existingClass = node.attributes.class || '';
                          const newClass = colorClassMapping[lowerCaseStroke];
                          if (!existingClass.includes(newClass)) {
                            node.attributes.class =
                              `${existingClass} ${newClass}`.trim();
                          }
                        }
                      }
                    },
                  },
                };
              },
            },
          ],
        },
      },
    }),
  ],
  base: process.env.PATH_PREFIX ? `${process.env.PATH_PREFIX}/` : '/',
  define: {
    'import.meta.env.VERCEL': JSON.stringify(process.env.VERCEL),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@config': path.resolve(__dirname, 'config.yml'),
      '@core': path.resolve(__dirname, './src/core'),
      '@themes': path.resolve(__dirname, './src/themes'),
      '@assets': path.resolve(__dirname, './assets'),
    },
  },
  build: {
    manifest: true,
    modulePreload: false,
    outDir: './dist',
  },
});
