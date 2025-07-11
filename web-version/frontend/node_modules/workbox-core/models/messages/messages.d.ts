import '../../_version.js';
interface LoggableObject {
    [key: string]: string | number;
}
interface MessageMap {
    [messageID: string]: (param: LoggableObject) => string;
}
export declare const messages: MessageMap;
export {};
