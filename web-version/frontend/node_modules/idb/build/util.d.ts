export declare type Constructor = new (...args: any[]) => any;
export declare type Func = (...args: any[]) => any;
export declare const instanceOfAny: (object: any, constructors: Constructor[]) => boolean;
