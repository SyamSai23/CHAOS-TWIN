import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { API_BASE } from "../api/client";

type FeatureFile = {
  path: string;
  file_type: string;
  summary: string;
  importance_score: number;
};

type Feature = {
  name: string;
  description: string;
  entry_point: string;
  files: string[];
  importance: number;
  file_details?: FeatureFile[];
  files_detail?: FeatureFile[];
};

type FeatureMapPageProps = {
  projectId: string;
};

type Connection = {
  from: number;
  to: number;
  sharedFiles: string[];
};

type FeatureHealth = {
  fileCount: number;
  hasTests: boolean;
  externalDepCount: number;
  risk: "low" | "medium" | "high";
  riskEmoji: "🟢" | "🟡" | "🔴";
};

type TooltipState = {
  x: number;
  y: number;
  files: string[];
  featureA: string;
  featureB: string;
} | null;

type NodePosition = {
  x: number;
  y: number;
};

const FILE_TYPE_COLORS: Record<string, string> = {
  controller: "#4a7c59",
  model: "#705c30",
  entry_point: "#c0392b",
  service: "#2980b9",
  config: "#8e44ad",
  route: "#e67e22",
  other: "#74796e",
};

function getFileTypeColor(fileType: string) {
  return FILE_TYPE_COLORS[fileType] ?? FILE_TYPE_COLORS.other;
}

function getFeatureKey(feature: Feature) {
  return `${feature.name}-${feature.entry_point}`;
}

function getFeatureFiles(feature: Feature) {
  return feature.files_detail
    ?? feature.file_details
    ?? feature.files.map((path) => ({
      path,
      file_type: "other",
      summary: "",
      importance_score: 0,
    }));
}

function getSharedFileName(file: unknown) {
  if (typeof file === "string") {
    return file.split("/").pop() || file;
  }

  if (file && typeof file === "object") {
    const candidate = file as { name?: string; file_name?: string; path?: string };
    return candidate.name
      || candidate.file_name
      || candidate.path?.split("/").pop()
      || "";
  }

  return "";
}

export default function FeatureMapPage({ projectId }: FeatureMapPageProps) {
  const [features, setFeatures] = useState<Feature[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFeature, setSelectedFeature] = useState<Feature | null>(null);
  const [nodePositions, setNodePositions] = useState<NodePosition[]>([]);
  const [canvasHeight, setCanvasHeight] = useState(760);
  const [containerWidth, setContainerWidth] = useState(0);
  const [cardHeights, setCardHeights] = useState<number[]>([]);
  const [hoveredConn, setHoveredConn] = useState<number | null>(null);
  const [openContextCard, setOpenContextCard] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);

  const connections = useMemo<Connection[]>(() => {
    if (!features || features.length < 2) {
      return [];
    }

    const result: Connection[] = [];
    for (let i = 0; i < features.length; i += 1) {
      for (let j = i + 1; j < features.length; j += 1) {
        const filesA = new Set(
          ((features[i].files || []) as unknown[])
            .map((file) => getSharedFileName(file))
            .filter(Boolean),
        );
        const sharedFiles = ((features[j].files || []) as unknown[])
          .map((file) => getSharedFileName(file))
          .filter((name): name is string => Boolean(name) && filesA.has(name));

        if (sharedFiles.length > 0) {
          result.push({
            from: i,
            to: j,
            sharedFiles,
          });
        }
      }
    }

    return result;
  }, [features]);

  const infrastructureFiles = useMemo(() => {
    if (!features || features.length === 0) {
      return [];
    }

    const fileFeatureCount: Record<string, { count: number; features: string[] }> = {};

    features.forEach((feature) => {
      const featureName = feature.name || "Unknown";
      (feature.files || []).forEach((file: unknown) => {
        const name = getSharedFileName(file);
        if (!name) {
          return;
        }

        if (!fileFeatureCount[name]) {
          fileFeatureCount[name] = { count: 0, features: [] };
        }

        if (!fileFeatureCount[name].features.includes(featureName)) {
          fileFeatureCount[name].count += 1;
          fileFeatureCount[name].features.push(featureName);
        }
      });
    });

    return Object.entries(fileFeatureCount)
      .filter(([, data]) => data.count >= 3)
      .sort((a, b) => b[1].count - a[1].count)
      .map(([fileName, data]) => ({ fileName, ...data }));
  }, [features]);

  const fileToFeatures = useMemo(() => {
    const map: Record<string, string[]> = {};

    (features || []).forEach((feature) => {
      const featureName = feature.name || "Unknown";
      (feature.files || []).forEach((file: unknown) => {
        const name = getSharedFileName(file);
        if (!name) {
          return;
        }

        if (!map[name]) {
          map[name] = [];
        }

        if (!map[name].includes(featureName)) {
          map[name].push(featureName);
        }
      });
    });

    return map;
  }, [features]);

  const featureHealthMap = useMemo(() => {
    const map: Record<string, FeatureHealth> = {};

    (features || []).forEach((feature) => {
      const featureName = feature.name || "Unknown";
      const files = feature.files || [];
      const fileCount = files.length;

      const hasTests = files.some((file: unknown) => {
        const name = (typeof file === "string"
          ? file
          : (file as { name?: string; file_name?: string; path?: string }).name
            || (file as { name?: string; file_name?: string; path?: string }).file_name
            || (file as { name?: string; file_name?: string; path?: string }).path
            || "").toLowerCase();
        return name.includes("test") || name.includes("spec");
      });

      const externalDepCount = files.filter((file: unknown) => {
        if (typeof file === "string") {
          const name = file.toLowerCase();
          return name.includes("api") || name.includes("service") || name.includes("client");
        }

        const candidate = file as { name?: string; file_name?: string; type?: string; file_type?: string };
        const name = (candidate.name || candidate.file_name || "").toLowerCase();
        const type = (candidate.type || candidate.file_type || "").toLowerCase();
        return type === "external" || name.includes("api") || name.includes("service") || name.includes("client");
      }).length;

      let riskScore = 0;
      if (fileCount > 8) {
        riskScore += 2;
      } else if (fileCount > 4) {
        riskScore += 1;
      }
      if (!hasTests) {
        riskScore += 2;
      }
      if (externalDepCount >= 2) {
        riskScore += 2;
      } else if (externalDepCount === 1) {
        riskScore += 1;
      }

      const risk: FeatureHealth["risk"] = riskScore >= 4 ? "high" : riskScore >= 2 ? "medium" : "low";
      const riskEmoji: FeatureHealth["riskEmoji"] = risk === "high" ? "🔴" : risk === "medium" ? "🟡" : "🟢";

      map[featureName] = { fileCount, hasTests, externalDepCount, risk, riskEmoji };
    });

    return map;
  }, [features]);

  const featureContextMap = useMemo(() => {
    const map: Record<string, {
      relatedFeatures: { name: string; sharedFiles: string[] }[];
      riskiestFile: string | null;
    }> = {};

    (features || []).forEach((feature, index) => {
      const featureName = feature.name || "Unknown";

      const relatedFeatures = connections
        .filter((connection) => connection.from === index || connection.to === index)
        .map((connection) => {
          const otherIndex = connection.from === index ? connection.to : connection.from;
          const otherFeature = features[otherIndex];
          return {
            name: otherFeature?.name || "Unknown",
            sharedFiles: connection.sharedFiles,
          };
        })
        .sort((a, b) => b.sharedFiles.length - a.sharedFiles.length);

      const files = feature.files || [];
      let riskiestFile: string | null = null;
      let maxShared = 0;
      files.forEach((file: unknown) => {
        const name = getSharedFileName(file);
        const sharedCount = (fileToFeatures[name] || []).length;
        if (sharedCount > maxShared) {
          maxShared = sharedCount;
          riskiestFile = name;
        }
      });

      map[featureName] = { relatedFeatures, riskiestFile };
    });

    return map;
  }, [connections, features, fileToFeatures]);

  const openContextFeature = useMemo(
    () => features.find((feature) => (feature.name || "Unknown") === openContextCard) || null,
    [features, openContextCard],
  );

  const openContextData = useMemo(
    () => (openContextCard ? featureContextMap[openContextCard] || null : null),
    [featureContextMap, openContextCard],
  );

  useLayoutEffect(() => {
    if (selectedFeature) {
      return;
    }

    if (!containerRef.current) {
      return;
    }

    const measure = () => {
      setContainerWidth(containerRef.current?.offsetWidth || 0);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
    };
  }, [selectedFeature, features.length]);

  const estimatedCardHeights = useMemo(() => {
    return features.map((feature) => {
      const previewFiles = Math.min(getFeatureFiles(feature).length, 4);
      const descriptionLines = Math.min(3, Math.max(1, Math.ceil((feature.description || "").length / 42)));
      return 182 + (previewFiles * 30) + (descriptionLines * 20) + 48;
    });
  }, [features]);

  const featureConnectivity = useMemo(() => {
    return features.map((feature, index) => {
      let connectionWeight = 0;
      let connectionCount = 0;

      connections.forEach((connection) => {
        if (connection.from === index || connection.to === index) {
          connectionWeight += connection.sharedFiles.length;
          connectionCount += 1;
        }
      });

      return {
        index,
        importance: feature.importance || 0,
        connectionWeight,
        connectionCount,
      };
    });
  }, [connections, features]);

  useLayoutEffect(() => {
    if (selectedFeature) {
      return;
    }

    if (!features.length || !containerWidth) {
      setCardHeights([]);
      setNodePositions([]);
      setCanvasHeight(760);
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      setCardHeights(
        features.map((_, index) => cardRefs.current[index]?.offsetHeight || estimatedCardHeights[index] || 260),
      );
    });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [containerWidth, estimatedCardHeights, features, selectedFeature]);

  useLayoutEffect(() => {
    if (selectedFeature) {
      return;
    }

    if (!features.length || !containerWidth) {
      setNodePositions([]);
      setCanvasHeight(760);
      return;
    }

    const CARD_W = 280;
    const CARD_HALF = CARD_W / 2;
    const OUTER_GUTTER = 36;
    const VERTICAL_GAP = 34;
    const laneCount = containerWidth >= 1320 ? 3 : containerWidth >= 920 ? 2 : 1;
    const heights = features.map((_, index) => cardHeights[index] || estimatedCardHeights[index] || 260);
    const ranked = [...featureConnectivity].sort((a, b) => (
      b.connectionWeight - a.connectionWeight
      || b.connectionCount - a.connectionCount
      || b.importance - a.importance
      || a.index - b.index
    ));
    const lanes: number[][] = Array.from({ length: laneCount }, () => []);
    const laneHeights = Array(laneCount).fill(0);

    if (laneCount === 1) {
      ranked.forEach((item) => {
        lanes[0].push(item.index);
        laneHeights[0] += heights[item.index] + VERTICAL_GAP;
      });
    } else if (laneCount === 2) {
      ranked.forEach((item, order) => {
        const targetLane = order < 2 ? order : (laneHeights[0] <= laneHeights[1] ? 0 : 1);
        lanes[targetLane].push(item.index);
        laneHeights[targetLane] += heights[item.index] + VERTICAL_GAP;
      });
    } else {
      const centerQuota = Math.min(3, Math.max(1, Math.ceil(ranked.length / 3)));
      ranked.forEach((item, order) => {
        const targetLane = order < centerQuota ? 1 : (laneHeights[0] <= laneHeights[2] ? 0 : 2);
        lanes[targetLane].push(item.index);
        laneHeights[targetLane] += heights[item.index] + VERTICAL_GAP;
      });
    }

    const connectivityByIndex = new Map(featureConnectivity.map((item) => [item.index, item]));
    const orderLane = (indices: number[]) => {
      const sorted = [...indices].sort((a, b) => {
        const featureA = connectivityByIndex.get(a);
        const featureB = connectivityByIndex.get(b);
        if (!featureA || !featureB) {
          return a - b;
        }

        return (
          featureB.connectionWeight - featureA.connectionWeight
          || featureB.connectionCount - featureA.connectionCount
          || featureB.importance - featureA.importance
          || a - b
        );
      });

      const arranged: number[] = [];
      sorted.forEach((index, order) => {
        if (order % 2 === 0) {
          arranged.unshift(index);
        } else {
          arranged.push(index);
        }
      });
      return arranged;
    };

    const orderedLanes = lanes.map(orderLane);
    const xPositions = laneCount === 1
      ? [containerWidth / 2]
      : laneCount === 2
        ? [
            Math.max(CARD_HALF + OUTER_GUTTER, containerWidth * 0.32),
            Math.min(containerWidth - CARD_HALF - OUTER_GUTTER, containerWidth * 0.68),
          ]
        : [
            CARD_HALF + OUTER_GUTTER,
            containerWidth / 2,
            containerWidth - CARD_HALF - OUTER_GUTTER,
          ];
    const laneContentHeights = orderedLanes.map((indices) => (
      indices.reduce((sum, index) => sum + heights[index], 0) + Math.max(indices.length - 1, 0) * VERTICAL_GAP
    ));
    const maxLaneHeight = Math.max(620, ...laneContentHeights);
    const nextPositions: NodePosition[] = Array.from({ length: features.length }, () => ({ x: 0, y: 0 }));

    orderedLanes.forEach((indices, laneIndex) => {
      let currentY = OUTER_GUTTER + ((maxLaneHeight - laneContentHeights[laneIndex]) / 2);
      indices.forEach((index) => {
        nextPositions[index] = {
          x: xPositions[laneIndex],
          y: currentY + (heights[index] / 2),
        };
        currentY += heights[index] + VERTICAL_GAP;
      });
    });

    setNodePositions(nextPositions);
    setCanvasHeight(Math.ceil(maxLaneHeight + (OUTER_GUTTER * 2)));
  }, [cardHeights, containerWidth, estimatedCardHeights, featureConnectivity, features, selectedFeature]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setOpenContextCard(null);
    setSelectedFeature(null);
    setHoveredConn(null);
    setTooltip(null);
    setNodePositions([]);
    setCanvasHeight(760);
    setCardHeights([]);

    fetch(`${API_BASE}/projects/${projectId}/feature-map`)
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || "Failed to load feature map");
        }
        return body;
      })
      .then((body) => {
        if (!cancelled) {
          const nextFeatures = Array.isArray(body?.features) ? body.features : [];
          setFeatures(nextFeatures);
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : "Failed to load feature map");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    cardRefs.current = cardRefs.current.slice(0, features.length);
  }, [features.length]);

  function findEntryPointDetail(feature: Feature) {
    const details = getFeatureFiles(feature);
    const directMatch = details.find((file) => file.path === feature.entry_point);
    if (directMatch) {
      return directMatch;
    }
    const entryName = feature.entry_point.split("/").pop();
    return details.find((file) => file.path.split("/").pop() === entryName) ?? null;
  }

  if (loading) {
    return (
      <div
        style={{
          minHeight: "calc(100vh - 120px)",
          display: "grid",
          placeItems: "center",
          background: "#faf6f0",
          borderRadius: 18,
          color: "#2e3230",
          fontFamily: "'Nunito Sans', sans-serif",
        }}
      >
        <div style={{ display: "grid", placeItems: "center", gap: 12 }}>
          <Loader2 size={28} style={{ color: "#4a7c59", animation: "terra-spin 1s linear infinite" }} />
          <div style={{ fontSize: 15, color: "#74796e" }}>Mapping features...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          minHeight: "calc(100vh - 120px)",
          background: "#faf6f0",
          borderRadius: 18,
          padding: 24,
          color: "#c0392b",
          fontFamily: "'Nunito Sans', sans-serif",
        }}
      >
        {error}
      </div>
    );
  }

  return (
    <>
      <div
        style={{
          minHeight: "calc(100vh - 120px)",
          background: "#faf6f0",
          borderRadius: 18,
          padding: 24,
          color: "#2e3230",
          fontFamily: "'Nunito Sans', sans-serif",
        }}
      >
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ margin: 0, fontFamily: "'Literata', serif", fontSize: 34, color: "#2e3230" }}>Feature Map</h1>
          <p style={{ margin: "8px 0 0", color: "#74796e", fontSize: 14 }}>
            The main capabilities of this codebase, grouped for a junior developer.
          </p>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: selectedFeature ? "220px minmax(0, 1fr)" : "1fr",
            gap: 20,
            alignItems: "start",
            transition: "grid-template-columns 300ms ease",
          }}
        >
          {selectedFeature ? (
            <>
              <aside
                style={{
                  width: 220,
                  minWidth: 220,
                  transition: "width 300ms ease",
                }}
              >
                <button
                  type="button"
                  onClick={() => setSelectedFeature(null)}
                  style={{
                    border: "none",
                    background: "transparent",
                    padding: 0,
                    marginBottom: 14,
                    color: "#4a7c59",
                    fontSize: 14,
                    fontWeight: 700,
                    cursor: "pointer",
                    fontFamily: "'Nunito Sans', sans-serif",
                  }}
                >
                  ← All Features
                </button>

                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  {features.map((feature) => {
                    const active = getFeatureKey(feature) === getFeatureKey(selectedFeature);
                    return (
                      <button
                        key={getFeatureKey(feature)}
                        type="button"
                        onClick={() => setSelectedFeature(feature)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: 12,
                          border: "1px solid rgba(196,200,188,0.45)",
                          borderLeft: active ? "3px solid #4a7c59" : "3px solid transparent",
                          borderRadius: 12,
                          background: active ? "#f5f1ea" : "rgba(250,246,240,0.8)",
                          color: "#2e3230",
                          cursor: "pointer",
                          textAlign: "left",
                          fontFamily: "'Nunito Sans', sans-serif",
                        }}
                      >
                        <span
                          style={{
                            width: 9,
                            height: 9,
                            borderRadius: "50%",
                            background: "#4a7c59",
                            flexShrink: 0,
                          }}
                        />
                        <span
                          style={{
                            minWidth: 0,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            fontSize: 13,
                            fontWeight: active ? 700 : 600,
                          }}
                        >
                          {feature.name}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </aside>

              <section
                style={{
                  display: "flex",
                  justifyContent: "center",
                  transition: "all 300ms ease",
                }}
              >
                <article
                  style={{
                    width: "65%",
                    minWidth: 0,
                    background: "#f5f1ea",
                    border: "1px solid #4a7c59",
                    borderRadius: 12,
                    padding: 24,
                    boxShadow: "0 8px 28px rgba(46,50,48,0.10)",
                    display: "flex",
                    flexDirection: "column",
                    gap: 18,
                    transition: "all 300ms ease",
                  }}
                >
                  <div style={{ fontFamily: "'Literata', serif", color: "#2e3230", fontSize: 24, fontWeight: 700 }}>
                    {selectedFeature.name}
                  </div>

                  <div style={{ color: "#74796e", fontSize: 15, lineHeight: 1.7 }}>
                    {selectedFeature.description}
                  </div>

                  <div
                    style={{
                      width: "100%",
                      height: 4,
                      borderRadius: 999,
                      background: "rgba(196,200,188,0.48)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${Math.max(0, Math.min(100, (selectedFeature.importance || 0) * 100))}%`,
                        height: "100%",
                        background: "#4a7c59",
                      }}
                    />
                  </div>

                  <div style={{ marginTop: 24 }}>
                    <div
                      style={{
                        color: "#4a7c59",
                        fontSize: 11,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        fontWeight: 700,
                        marginBottom: 8,
                      }}
                    >
                      Start here
                    </div>

                    <div
                      style={{
                        display: "inline-block",
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                        background: "#f5f1ea",
                        border: "1px solid #c4c8bc",
                        borderRadius: 6,
                        padding: "4px 10px",
                        fontSize: 13,
                        color: "#2e3230",
                      }}
                    >
                      {selectedFeature.entry_point}
                    </div>

                    <div
                      style={{
                        marginTop: 8,
                        color: "#74796e",
                        fontSize: 13,
                        fontStyle: "italic",
                        lineHeight: 1.6,
                      }}
                    >
                      {findEntryPointDetail(selectedFeature)?.summary || ""}
                    </div>
                  </div>

                  <div style={{ marginTop: 24 }}>
                    <div
                      style={{
                        color: "#4a7c59",
                        fontSize: 11,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        fontWeight: 700,
                        marginBottom: 12,
                      }}
                    >
                      Files in this feature
                    </div>

                    <div>
                      {getFeatureFiles(selectedFeature).map((file, index, arr) => (
                        <div
                          key={file.path}
                          style={{
                            padding: "8px 0",
                            borderBottom: index < arr.length - 1 ? "1px solid #f0ece4" : "none",
                          }}
                        >
                          {(() => {
                            const fileName = file.path.split("/").pop() || "";
                            const alsoUsedBy = (fileToFeatures[fileName] || []).filter(
                              (name) => name !== selectedFeature.name,
                            );

                            return (
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "flex-start",
                                  gap: 8,
                                  minWidth: 0,
                                }}
                              >
                                <span
                                  style={{
                                    width: 8,
                                    height: 8,
                                    borderRadius: "50%",
                                    background: getFileTypeColor(file.file_type),
                                    flexShrink: 0,
                                    marginTop: 5,
                                  }}
                                />

                                <div
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    flexWrap: "wrap",
                                    gap: 6,
                                    minWidth: 0,
                                    flex: 1,
                                  }}
                                >
                                  <span
                                    style={{
                                      minWidth: 0,
                                      overflow: "hidden",
                                      textOverflow: "ellipsis",
                                      whiteSpace: "nowrap",
                                      color: "#2e3230",
                                      fontSize: 13,
                                      fontWeight: 700,
                                    }}
                                  >
                                    {fileName}
                                  </span>

                                  {alsoUsedBy.map((otherFeature) => {
                                    const otherIndex = (features || []).findIndex(
                                      (featureItem) => featureItem.name === otherFeature,
                                    );

                                    return (
                                      <span
                                        key={otherFeature}
                                        onClick={(event) => {
                                          event.stopPropagation();
                                          if (otherIndex !== -1) {
                                            setSelectedFeature(features[otherIndex]);
                                          }
                                        }}
                                        title={`Also used by ${otherFeature} — click to jump there`}
                                        style={{
                                          fontSize: 10,
                                          color: "#4a7c59",
                                          background: "#eef4f1",
                                          border: "1px solid #4a7c59",
                                          borderRadius: 6,
                                          padding: "1px 7px",
                                          cursor: "pointer",
                                          fontWeight: 500,
                                          whiteSpace: "nowrap",
                                          transition: "background 0.15s",
                                        }}
                                        onMouseEnter={(event) => {
                                          event.currentTarget.style.background = "#d6ebe0";
                                        }}
                                        onMouseLeave={(event) => {
                                          event.currentTarget.style.background = "#eef4f1";
                                        }}
                                      >
                                        ↗ {otherFeature}
                                      </span>
                                    );
                                  })}
                                </div>

                                <span
                                  style={{
                                    marginLeft: "auto",
                                    padding: "4px 8px",
                                    borderRadius: 999,
                                    background: `${getFileTypeColor(file.file_type)}18`,
                                    color: getFileTypeColor(file.file_type),
                                    fontSize: 11,
                                    fontWeight: 700,
                                    flexShrink: 0,
                                  }}
                                >
                                  {file.file_type}
                                </span>
                              </div>
                            );
                          })()}

                          <div
                            style={{
                              marginTop: 4,
                              color: "#74796e",
                              fontSize: 11,
                              lineHeight: 1.5,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {file.path}
                          </div>

                          <div
                            style={{
                              marginTop: 6,
                              color: "#74796e",
                              fontSize: 12,
                              lineHeight: 1.5,
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                            }}
                          >
                            {file.summary}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </article>
              </section>
            </>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: openContextData ? "minmax(0, 1fr) 340px" : "1fr",
                gap: 24,
                alignItems: "start",
              }}
            >
              <div
                ref={containerRef}
                style={{
                  position: "relative",
                  width: "100%",
                  minHeight: "680px",
                  height: `${canvasHeight}px`,
                  overflow: "visible",
                  borderRadius: 24,
                  background: "linear-gradient(180deg, rgba(245,241,234,0.55) 0%, rgba(250,246,240,0.9) 100%)",
                }}
              >
                {features.length > 0 && nodePositions.length === 0 ? (
                  <div style={{ padding: 40, color: "#74796e" }}>Mapping feature relationships…</div>
                ) : null}

                {nodePositions.length === features.length ? (
                  <svg
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: "100%",
                      pointerEvents: "none",
                      overflow: "visible",
                      zIndex: 0,
                    }}
                  >
                    <defs>
                      <filter id="glow">
                        <feGaussianBlur stdDeviation="2.5" result="coloredBlur" />
                        <feMerge>
                          <feMergeNode in="coloredBlur" />
                          <feMergeNode in="SourceGraphic" />
                        </feMerge>
                      </filter>
                    </defs>
                    {connections.map((conn, index) => {
                      const a = nodePositions[conn.from];
                      const b = nodePositions[conn.to];
                      if (!a || !b) {
                        return null;
                      }

                      const strokeWidth = Math.min(1.5 + (conn.sharedFiles.length * 1.2), 7);
                      const isHovered = hoveredConn === index;
                      const mx = (a.x + b.x) / 2;
                      const my = ((a.y + b.y) / 2) - 30;

                      return (
                        <g key={`${conn.from}-${conn.to}-${index}`}>
                          <path
                            id={`conn-${index}`}
                            d={`M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`}
                            stroke="#4a7c59"
                            strokeWidth={strokeWidth}
                            strokeOpacity={isHovered ? 1 : 0.35}
                            strokeLinecap="round"
                            fill="none"
                            filter={isHovered ? "url(#glow)" : undefined}
                            style={{ pointerEvents: "stroke", cursor: "pointer" }}
                            onMouseEnter={(event) => {
                              setHoveredConn(index);
                              setTooltip({
                                x: event.clientX,
                                y: event.clientY,
                                files: conn.sharedFiles,
                                featureA: features[conn.from]?.name || "Feature A",
                                featureB: features[conn.to]?.name || "Feature B",
                              });
                            }}
                            onMouseMove={(event) => {
                              setTooltip((current) => (current ? {
                                ...current,
                                x: event.clientX,
                                y: event.clientY,
                              } : null));
                            }}
                            onMouseLeave={() => {
                              setHoveredConn(null);
                              setTooltip(null);
                            }}
                          />
                          <circle r="3" fill="#4a7c59" opacity="0.7">
                            <animateMotion dur={`${2.5 + (conn.sharedFiles.length * 0.4)}s`} repeatCount="indefinite">
                              <mpath href={`#conn-${index}`} />
                            </animateMotion>
                          </circle>
                        </g>
                      );
                    })}
                  </svg>
                ) : null}

                {features.map((feature, index) => {
                  const position = nodePositions[index];
                  if (!position) {
                    return null;
                  }

                  const featureName = feature.name || "Unknown";
                  const featureFiles = getFeatureFiles(feature);
                  const previewFiles = featureFiles.slice(0, 4);
                  const hiddenFileCount = Math.max(0, featureFiles.length - previewFiles.length);
                  const isContextOpen = openContextCard === featureName;

                  return (
                    <div
                      key={getFeatureKey(feature)}
                      ref={(element) => {
                        cardRefs.current[index] = element;
                      }}
                      onClick={() => setSelectedFeature(feature)}
                      style={{
                        position: "absolute",
                        left: position.x,
                        top: position.y,
                        width: 280,
                        cursor: "pointer",
                        zIndex: isContextOpen ? 2 : 1,
                        transform: "translate(-50%, -50%)",
                        transition: "transform 300ms ease",
                      }}
                      onMouseEnter={(event) => {
                        const card = event.currentTarget.firstElementChild as HTMLElement | null;
                        if (card) {
                          card.style.borderColor = "#4a7c59";
                        }
                        event.currentTarget.style.transform = "translate(-50%, calc(-50% - 2px))";
                      }}
                      onMouseLeave={(event) => {
                        const card = event.currentTarget.firstElementChild as HTMLElement | null;
                        if (card) {
                          card.style.borderColor = isContextOpen ? "#4a7c59" : "#c4c8bc";
                        }
                        event.currentTarget.style.transform = "translate(-50%, -50%)";
                      }}
                    >
                      <article
                        style={{
                          background: isContextOpen ? "#f8f5ee" : "#f5f1ea",
                          border: isContextOpen ? "1.5px solid #4a7c59" : "1px solid #c4c8bc",
                          borderRadius: 16,
                          padding: 24,
                          boxShadow: isContextOpen ? "0 14px 32px rgba(74,124,89,0.14)" : "0 4px 20px rgba(46,50,48,0.06)",
                          display: "flex",
                          flexDirection: "column",
                          gap: 18,
                          position: "relative",
                          zIndex: 1,
                          overflow: "hidden",
                          transition: "transform 300ms ease, border-color 300ms ease, box-shadow 300ms ease, background 300ms ease",
                        }}
                      >
                      <div>
                        <div style={{ fontFamily: "'Literata', serif", color: "#2e3230", fontSize: 18, fontWeight: 700 }}>
                          {feature.name}
                        </div>
                        <div
                          style={{
                            marginTop: 8,
                            color: "#74796e",
                            fontSize: 14,
                            lineHeight: 1.6,
                            display: "-webkit-box",
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                          }}
                        >
                          {feature.description}
                        </div>
                      </div>

                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        {previewFiles.map((file) => (
                          <span
                            key={file.path}
                            title={file.path}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                              padding: "6px 10px",
                              borderRadius: 999,
                              background: `${getFileTypeColor(file.file_type)}18`,
                              color: getFileTypeColor(file.file_type),
                              fontSize: 12,
                              fontWeight: 700,
                              maxWidth: "100%",
                            }}
                          >
                            <span
                              style={{
                                width: 8,
                                height: 8,
                                borderRadius: "50%",
                                background: getFileTypeColor(file.file_type),
                                flexShrink: 0,
                              }}
                            />
                            <span
                              style={{
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {file.path.split("/").pop()}
                            </span>
                          </span>
                        ))}
                        {hiddenFileCount > 0 ? (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                              padding: "6px 10px",
                              borderRadius: 999,
                              background: "#ede8df",
                              color: "#74796e",
                              fontSize: 12,
                              fontWeight: 700,
                              maxWidth: "100%",
                            }}
                          >
                            +{hiddenFileCount} more
                          </span>
                        ) : null}
                      </div>

                        <div
                          style={{
                            alignSelf: "flex-start",
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                            background: "#faf6f0",
                            border: "1px solid #c4c8bc",
                            borderRadius: 6,
                            padding: "2px 8px",
                            color: "#545e57",
                            fontSize: 12,
                          }}
                        >
                          {feature.entry_point}
                        </div>

                        {(() => {
                          const featureName = feature.name || "Unknown";
                          const health = featureHealthMap[featureName];
                          if (!health) {
                            return null;
                          }

                          return (
                            <div
                              style={{
                                marginTop: 12,
                                paddingTop: 10,
                                borderTop: "1px solid #e8e4dc",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                gap: 8,
                              }}
                            >
                              <span
                                style={{
                                  fontSize: 12,
                                  fontWeight: 600,
                                  color: health.risk === "high" ? "#dc2626" : health.risk === "medium" ? "#d97706" : "#4a7c59",
                                }}
                              >
                                {health.riskEmoji} {health.risk === "high" ? "High risk" : health.risk === "medium" ? "Medium risk" : "Low risk"}
                              </span>

                              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                                <span
                                  style={{
                                    fontSize: 10,
                                    padding: "2px 7px",
                                    background: "#f0ede8",
                                    borderRadius: 6,
                                    color: "#74796e",
                                  }}
                                >
                                  {health.fileCount} files
                                </span>

                                {health.hasTests ? (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      padding: "2px 7px",
                                      background: "#eef4f1",
                                      borderRadius: 6,
                                      color: "#4a7c59",
                                    }}
                                  >
                                    ✓ tested
                                  </span>
                                ) : (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      padding: "2px 7px",
                                      background: "#fef3f2",
                                      borderRadius: 6,
                                      color: "#dc2626",
                                    }}
                                  >
                                    no tests
                                  </span>
                                )}

                                {health.externalDepCount > 0 ? (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      padding: "2px 7px",
                                      background: "#fefce8",
                                      borderRadius: 6,
                                      color: "#92400e",
                                    }}
                                  >
                                    {health.externalDepCount} external
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          );
                        })()}

                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            setOpenContextCard(isContextOpen ? null : featureName);
                          }}
                          style={{
                            marginTop: 10,
                            width: "100%",
                            padding: "8px 0",
                            background: isContextOpen ? "#4a7c59" : "transparent",
                            color: isContextOpen ? "#fff" : "#4a7c59",
                            border: "1.5px solid #4a7c59",
                            borderRadius: 10,
                            fontSize: 12,
                            fontWeight: 700,
                            cursor: "pointer",
                            transition: "all 0.15s",
                          }}
                          onMouseEnter={(event) => {
                            if (!isContextOpen) {
                              event.currentTarget.style.background = "#eef4f1";
                            }
                          }}
                          onMouseLeave={(event) => {
                            if (!isContextOpen) {
                              event.currentTarget.style.background = "transparent";
                            }
                          }}
                        >
                          {isContextOpen ? "✕ Close context" : "⚡ Related context"}
                        </button>

                        <div
                          style={{
                            position: "absolute",
                            left: 0,
                            right: 0,
                            bottom: 0,
                            height: 3,
                            background: "rgba(196,200,188,0.48)",
                          }}
                        >
                          <div
                            style={{
                              width: `${Math.max(0, Math.min(100, (feature.importance || 0) * 100))}%`,
                              height: "100%",
                              background: "#4a7c59",
                            }}
                          />
                        </div>
                      </article>
                    </div>
                  );
                })}
              </div>

              {openContextData && openContextFeature ? (
                <aside
                  style={{
                    position: "sticky",
                    top: 24,
                    alignSelf: "start",
                    background: "linear-gradient(180deg, #f7f3ec 0%, #f1ece3 100%)",
                    border: "1px solid #c4c8bc",
                    borderRadius: 18,
                    padding: 20,
                    boxShadow: "0 12px 30px rgba(46,50,48,0.08)",
                    display: "flex",
                    flexDirection: "column",
                    gap: 18,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      justifyContent: "space-between",
                      gap: 12,
                    }}
                  >
                    <div>
                      <div
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          letterSpacing: "0.08em",
                          textTransform: "uppercase",
                          color: "#74796e",
                          marginBottom: 6,
                        }}
                      >
                        Context Lens
                      </div>
                      <div style={{ fontFamily: "'Literata', serif", fontSize: 24, color: "#2e3230", fontWeight: 700 }}>
                        {openContextFeature.name}
                      </div>
                      <div style={{ marginTop: 8, color: "#74796e", fontSize: 14, lineHeight: 1.6 }}>
                        {openContextFeature.description}
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => setOpenContextCard(null)}
                      style={{
                        border: "none",
                        background: "transparent",
                        color: "#74796e",
                        cursor: "pointer",
                        fontSize: 20,
                        lineHeight: 1,
                        padding: 0,
                      }}
                    >
                      ×
                    </button>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                      gap: 10,
                    }}
                  >
                    <div
                      style={{
                        background: "#fff",
                        border: "1px solid #dfd8cd",
                        borderRadius: 12,
                        padding: "10px 12px",
                      }}
                    >
                      <div style={{ fontSize: 10, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Coupled features
                      </div>
                      <div style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: "#2e3230" }}>
                        {openContextData.relatedFeatures.length}
                      </div>
                    </div>
                    <div
                      style={{
                        background: "#fff",
                        border: "1px solid #dfd8cd",
                        borderRadius: 12,
                        padding: "10px 12px",
                      }}
                    >
                      <div style={{ fontSize: 10, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Shared files
                      </div>
                      <div style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: "#2e3230" }}>
                        {openContextData.relatedFeatures.reduce((sum, item) => sum + item.sharedFiles.length, 0)}
                      </div>
                    </div>
                    <div
                      style={{
                        background: "#fff",
                        border: "1px solid #dfd8cd",
                        borderRadius: 12,
                        padding: "10px 12px",
                      }}
                    >
                      <div style={{ fontSize: 10, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Impact file
                      </div>
                      <div
                        style={{
                          marginTop: 4,
                          fontSize: 12,
                          fontWeight: 700,
                          color: "#2e3230",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {openContextData.riskiestFile || "None"}
                      </div>
                    </div>
                  </div>

                  <div
                    style={{
                      background: "#fff",
                      border: "1px solid #dfd8cd",
                      borderRadius: 14,
                      padding: 16,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: "#74796e",
                        marginBottom: 10,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                      }}
                    >
                      Coupled with
                    </div>
                    {openContextData.relatedFeatures.length > 0 ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {openContextData.relatedFeatures.map((relatedFeature) => (
                          <button
                            key={relatedFeature.name}
                            type="button"
                            onClick={() => setOpenContextCard(relatedFeature.name)}
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              gap: 10,
                              width: "100%",
                              border: "none",
                              background: "#f7f3ec",
                              borderRadius: 10,
                              padding: "10px 12px",
                              cursor: "pointer",
                              textAlign: "left",
                            }}
                          >
                            <span style={{ fontSize: 13, color: "#2e3230", fontWeight: 600 }}>
                              {relatedFeature.name}
                            </span>
                            <span
                              style={{
                                fontSize: 10,
                                color: relatedFeature.sharedFiles.length >= 3 ? "#dc2626" : relatedFeature.sharedFiles.length >= 2 ? "#d97706" : "#4a7c59",
                                background: relatedFeature.sharedFiles.length >= 3 ? "#fef3f2" : relatedFeature.sharedFiles.length >= 2 ? "#fefce8" : "#eef4f1",
                                padding: "3px 8px",
                                borderRadius: 999,
                                fontWeight: 600,
                                whiteSpace: "nowrap",
                              }}
                            >
                              {relatedFeature.sharedFiles.length} shared file{relatedFeature.sharedFiles.length > 1 ? "s" : ""}
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div style={{ fontSize: 13, color: "#74796e" }}>
                        This feature stands on its own with no direct coupling.
                      </div>
                    )}
                  </div>

                  {openContextData.riskiestFile && (fileToFeatures[openContextData.riskiestFile] || []).length > 1 ? (
                    <div
                      style={{
                        background: "#fff4f2",
                        border: "1px solid #fecaca",
                        borderRadius: 14,
                        padding: 16,
                      }}
                    >
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#dc2626", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Riskiest file
                      </div>
                      <div style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace", fontSize: 13, color: "#2e3230" }}>
                        {openContextData.riskiestFile}
                      </div>
                      <div style={{ marginTop: 6, fontSize: 12, color: "#74796e", lineHeight: 1.5 }}>
                        Shared across {(fileToFeatures[openContextData.riskiestFile] || []).length} features, so edits here can ripple widely through the system.
                      </div>
                    </div>
                  ) : null}

                  <button
                    type="button"
                    onClick={() => setSelectedFeature(openContextFeature)}
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      borderRadius: 12,
                      border: "1px solid #4a7c59",
                      background: "#4a7c59",
                      color: "#fff",
                      fontSize: 13,
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    Open Full Feature
                  </button>
                </aside>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {tooltip ? (
        <div
          style={{
            position: "fixed",
            top: tooltip.y - 10,
            left: tooltip.x + 12,
            transform: "translateY(-100%)",
            background: "#2e3230",
            color: "#faf6f0",
            padding: "10px 14px",
            borderRadius: 10,
            fontSize: 12,
            pointerEvents: "none",
            zIndex: 9999,
            maxWidth: 240,
            boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
            lineHeight: 1.5,
          }}
        >
          <div
            style={{
              fontWeight: 700,
              marginBottom: 6,
              fontSize: 13,
              color: tooltip.files.length >= 4 ? "#f87171" : tooltip.files.length >= 2 ? "#fbbf24" : "#86b89a",
            }}
          >
            {tooltip.files.length >= 4 ? "🔴 Tightly coupled" : tooltip.files.length >= 2 ? "🟡 Moderately coupled" : "🟢 Loosely coupled"}
          </div>

          <div style={{ marginBottom: 8, opacity: 0.85 }}>
            {tooltip.featureA} and {tooltip.featureB} share {tooltip.files.length} file{tooltip.files.length > 1 ? "s" : ""} -
            changes to {tooltip.files.length >= 3 ? "either feature" : "one"} may affect the other.
          </div>

          <div style={{ borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: 6 }}>
            {tooltip.files.map((file) => (
              <div key={file} style={{ opacity: 0.65, fontFamily: "monospace", fontSize: 11 }}>{file}</div>
            ))}
          </div>
        </div>
      ) : null}

      {!selectedFeature && infrastructureFiles.length > 0 ? (
        <div style={{ marginTop: 48 }}>
          <div style={{ marginBottom: 16 }}>
            <h3
              style={{
                fontSize: 14,
                fontWeight: 700,
                color: "#2e3230",
                margin: 0,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: "#705c30",
                }}
              />
              Shared Infrastructure
            </h3>
            <p style={{ fontSize: 12, color: "#74796e", margin: "4px 0 0 18px" }}>
              These files are used by 3 or more features - they are the foundation of this codebase. Be careful when changing them.
            </p>
          </div>

          <div
            style={{
              background: "linear-gradient(135deg, #f5f1ea 0%, #ede8df 100%)",
              border: "1.5px solid #c4c8bc",
              borderRadius: 16,
              padding: "20px 24px",
              display: "flex",
              flexWrap: "wrap",
              gap: 12,
              position: "relative",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                position: "absolute",
                inset: 0,
                backgroundImage: "radial-gradient(circle, #c4c8bc 1px, transparent 1px)",
                backgroundSize: "20px 20px",
                opacity: 0.3,
                pointerEvents: "none",
              }}
            />

            {infrastructureFiles.map(({ fileName, count, features: usedBy }) => (
              <div
                key={fileName}
                title={`Used by: ${usedBy.join(", ")}`}
                style={{
                  background: "#fff",
                  border: "1.5px solid #c4c8bc",
                  borderRadius: 10,
                  padding: "8px 14px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  cursor: "default",
                  position: "relative",
                  zIndex: 1,
                  transition: "box-shadow 0.15s",
                  minWidth: 140,
                }}
                onMouseEnter={(event) => {
                  event.currentTarget.style.boxShadow = "0 4px 12px rgba(46,50,48,0.12)";
                }}
                onMouseLeave={(event) => {
                  event.currentTarget.style.boxShadow = "none";
                }}
              >
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "#2e3230",
                  }}
                >
                  {fileName}
                </span>

                <span
                  style={{
                    fontSize: 11,
                    color: "#705c30",
                    background: "#f5f1ea",
                    borderRadius: 6,
                    padding: "2px 6px",
                    alignSelf: "flex-start",
                    fontWeight: 500,
                  }}
                >
                  used in {count} features
                </span>

                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 2 }}>
                  {usedBy.map((featureName) => (
                    <span
                      key={featureName}
                      style={{
                        fontSize: 10,
                        color: "#74796e",
                        background: "#ede8df",
                        borderRadius: 4,
                        padding: "1px 5px",
                      }}
                    >
                      {featureName}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
