// import type { LoadingComponentProps } from "../../../types/components";

// export default function LoadingComponent({
//   remSize,
// }: LoadingComponentProps): JSX.Element {
//   return (
//     <div role="status" className="flex flex-col items-center justify-center">
//       <svg
//         aria-hidden="true"
//         className={`w-${remSize} h-${remSize} animate-spin fill-primary text-muted`}
//         viewBox="0 0 100 101"
//         fill="none"
//         xmlns="http://www.w3.org/2000/svg"
//       >
//         <path
//           d="M100 50.5908C100 78.2051 77.6142 100.591 50 100.591C22.3858 100.591 0 78.2051 0 50.5908C0 22.9766 22.3858 0.59082 50 0.59082C77.6142 0.59082 100 22.9766 100 50.5908ZM9.08144 50.5908C9.08144 73.1895 27.4013 91.5094 50 91.5094C72.5987 91.5094 90.9186 73.1895 90.9186 50.5908C90.9186 27.9921 72.5987 9.67226 50 9.67226C27.4013 9.67226 9.08144 27.9921 9.08144 50.5908Z"
//           fill="currentColor"
//         />
//         <path
//           d="M93.9676 39.0409C96.393 38.4038 97.8624 35.9116 97.0079 33.5539C95.2932 28.8227 92.871 24.3692 89.8167 20.348C85.8452 15.1192 80.8826 10.7238 75.2124 7.41289C69.5422 4.10194 63.2754 1.94025 56.7698 1.05124C51.7666 0.367541 46.6976 0.446843 41.7345 1.27873C39.2613 1.69328 37.813 4.19778 38.4501 6.62326C39.0873 9.04874 41.5694 10.4717 44.0505 10.1071C47.8511 9.54855 51.7191 9.52689 55.5402 10.0491C60.8642 10.7766 65.9928 12.5457 70.6331 15.2552C75.2735 17.9648 79.3347 21.5619 82.5849 25.841C84.9175 28.9121 86.7997 32.2913 88.1811 35.8758C89.083 38.2158 91.5421 39.6781 93.9676 39.0409Z"
//           fill="currentFill"
//         />
//       </svg>
//       <br></br>
//       <span className="animate-pulse text-lg text-primary">Loading...</span>
//     </div>
//   );
// }
import type { LoadingComponentProps } from "../../../types/components";

export default function LoadingComponent(_: LoadingComponentProps): JSX.Element {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center gap-3"
    >
      {/* Fixed-size loader */}
      <svg
        width="56"
        height="56"
        viewBox="0 0 72.7 81"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        <style>
          {`
            .bar {
              fill: #DA2020;
              opacity: 0.3;
              animation: fade 1.4s infinite ease-in-out;
            }

            .bar1 { animation-delay: 0s; }
            .bar2 { animation-delay: 0.2s; }
            .bar3 { animation-delay: 0.4s; }

            @keyframes fade {
              0%   { opacity: 0.3; }
              50%  { opacity: 1; }
              100% { opacity: 0.3; }
            }
          `}
        </style>

        <path
          className="bar bar1"
          d="M6.1,46.1C2.4,47.8,0,51.3,0,55.3V81h14.1c3.4,0,6.1-2.7,6.1-6.1V40.5L6.1,46.1z"
        />
        <path
          className="bar bar2"
          d="M32.3,26c-3.7,1.6-6.1,5.2-6.1,9.2V81h14.1c3.4,0,6.1-2.7,6.1-6.1V20.2L32.3,26z"
        />
        <path
          className="bar bar3"
          d="M58.6,5.6c-3.7,1.6-6.1,5.2-6.1,9.2V81h14.1c3.4,0,6.1-2.7,6.1-6.1V0L58.6,5.6z"
        />
      </svg>

    
    </div>
  );
}
