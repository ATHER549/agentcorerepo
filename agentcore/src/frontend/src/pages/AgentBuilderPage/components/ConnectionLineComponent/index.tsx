import type { ConnectionLineComponentProps } from "@xyflow/react";
import useAgentStore from "@/stores/agentStore";

const ConnectionLineComponent = ({
  fromX,
  fromY,
  toX,
  toY,
  connectionLineStyle = {},
}: ConnectionLineComponentProps): JSX.Element => {
  const handleDragging = useAgentStore((state) => state.handleDragging);
  const color = handleDragging?.color;
  const accentColor = `hsl(var(--datatype-${color}))`;

  return (
    <g>
      <path
        fill="none"
        // ! Replace hash # colors here
        strokeWidth={2}
        className={`animated`}
        style={{
          stroke: handleDragging ? accentColor : "",
          ...connectionLineStyle,
        }}
        d={`M${fromX},${fromY} C ${fromX} ${toY} ${fromX} ${toY} ${toX},${toY}`}
      />
      <circle
        cx={toX}
        cy={toY}
        fill="#fff"
        r={5}
        stroke={accentColor}
        className=""
        strokeWidth={1.5}
      />
    </g>
  );
};

export default ConnectionLineComponent;
