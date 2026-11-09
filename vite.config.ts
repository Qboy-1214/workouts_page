import process from 'node:process';
import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import yaml from '@modyfi/vite-plugin-yaml';
import svgr from 'vite-plugin-svgr';

// 把活动数据同步到固定路径 /data/activities.json 与 /data/activities.csv，
// 作为稳定的数据接口（URL 不随构建 hash 变化）。
function activitiesDataPlugin() {
  return {
    name: 'emit-activities-data',
    apply: 'build' as const,
    generateBundle() {
      const source = fs.readFileSync(
        path.resolve(__dirname, 'src/static/activities.json'),
        'utf-8',
      );
      this.emitFile({
        type: 'asset',
        fileName: 'data/activities.json',
        source,
      });

      // CSV 版本：字段与页面「下载数据」按钮一致
      const esc = (value: unknown) => {
        const s = String(value ?? '');
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
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
        run_id: number;
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
